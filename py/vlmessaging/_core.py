# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************


# Python imports
import itertools, logging, pynng, asyncio, weakref, collections, io, os, random, sys
from amazon.ion import simpleion

# local imports
from vlmessaging import _constants as VLM
from vlmessaging._utils.sentinels import Missing
from vlmessaging._utils.errors import NotYetImplemented, ProgrammerError
from vlmessaging._utils.co import until, taskOnEvent
from vlmessaging._utils.misc import firstValue
from vlmessaging._utils.pp import _PPMsg
from vlmessaging._utils.nng_et_al import pipeConnectionType
from vlmessaging._utils.utils import monotonicTimeMs, coPopFront, pushBack, corecv, Queue, cosend, dial, send


_logger = logging.getLogger(__name__)
random.seed(int.from_bytes(os.urandom(8), 'big'))
_routerIdSeed = itertools.count(os.getpid())    # OPEN: random number instead? any advantages or security concern about using pid?

_STOP_DIALING_ME_AND_CLOSE = "STOP_DIALING_ME_AND_CLOSE"

_DIRECTORY_CONNECTION_ID = 1
_FIRST_CONNECTION_ID = _DIRECTORY_CONNECTION_ID + 1
_MACHINE_HUB_ROUTER_ID = 0
_MAX_IPC_LISTEN_ATTEMPTS = 1000
_DEFAULT_HEARTBEAT_ENTRIES_INTERVAL = 10_000

_Details = collections.namedtuple('_Details', ('type', 'args'))
_MSG_ARRIVED = 1
_SOCK_RECV = 2
_TCP_RECV = 3
_TIMER = 4
_SHUTDOWN_TRIGGERED = 5
_TASKLIST_CHANGED = 6
_CONNECTION_ATTEMPT_TIMEOUT = 7

_eventPPNameById = {
    _MSG_ARRIVED: 'MSG_ARRIVED',
    _SOCK_RECV: 'SOCK_RECV',
    _TIMER: 'TIMER',
    _SHUTDOWN_TRIGGERED: 'SHUTDOWN_TRIGGERED',
    _TASKLIST_CHANGED: 'TASKLIST_CHANGED',
    _CONNECTION_ATTEMPT_TIMEOUT: 'CONNECTION_ATTEMPT_TIMEOUT',
}

_DEFAULT_LOCAL_CONNECTION_TIMESOUT = 2000

class ExitMessageHandler(Exception): pass


# **********************************************************************************************************************
# Public Structs
# **********************************************************************************************************************

Addr = collections.namedtuple('Addr', ('endpointId', 'routerId', 'connectionId'))
def Addr__str__(self):
    if self.routerId is None:
        return f'<{self.connectionId}>'
    elif self.endpointId is None:
        splits = self.routerId.rsplit('_', 1)
        return f'<{splits[-1]}:{self.connectionId}>'
    else:
        splits = self.routerId.rsplit('_', 1)
        return f'<{self.endpointId}:{splits[-1]}:{self.connectionId}>'
Addr.__str__ = Addr__str__


Entry = collections.namedtuple('Entry', ('addr', 'service', 'params', 'vnets', 'perms'))


Perm =  collections.namedtuple('Perm', ('domain', 'permId'))


class Msg:

    __slots__ = ('fromAddr', 'toAddr', 'subject', '_msgId', '_replyId', 'contents', 'meta')

    def __init__(self, toAddr, subject, contents=None):
        self.fromAddr = None
        self.toAddr = toAddr
        self.subject = subject
        self._msgId = None
        self._replyId = None
        self.contents = contents
        self.meta = {}

    def reply(self, contents, *, subject=Missing):
        answer = Msg(self.fromAddr, subject or self.subject, contents)
        answer._replyId = self._msgId
        return answer

    @property
    def isReply(self):
        return self._replyId is not None

    def __repr__(self):
        if self._replyId is None:
            return f'Msg({self.fromAddr!s} -> {self.toAddr!s} "{self.subject!s}" msgId: {self._msgId})'
        else:
            return f'Msg({self.fromAddr!s} -> {self.toAddr!s} "{self.subject!s}" REPLY msgId: {self._msgId}, replyId: {self._replyId})'



# **********************************************************************************************************************
# Connection
# **********************************************************************************************************************

class Connection:

    __slots__ = ('_router', '_msgArrivedFn', '_futureAndSubjectsByReplyId', '_msgIdSeed', 'addr', '__weakref__')

    def __init__(self, router, addr, fn):
        self._router = router
        self._msgArrivedFn = fn
        self._futureAndSubjectsByReplyId = {}
        self._msgIdSeed = itertools.count(1)
        self.addr = addr

    async def send(self, msg, timeout=Missing, additional_subjects=Missing):
        # return reply, Missing if timeout exceeded or None if no timeout
        msg._msgId = next(self._msgIdSeed)
        msg.fromAddr = self.addr
        if timeout:
            # semi-sync send - wait for reply or timeout
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            if additional_subjects is Missing:
                subjects = [msg.subject]
            else:
                subjects = [msg.subject] + additional_subjects
            self._futureAndSubjectsByReplyId[msg._msgId] = (fut, subjects)
            _PPMsg(f'send({timeout})', msg)
            self._router._route(msg)
            try:
                done, pending = await until(
                    (self._router._isShuttingDownTask, fut),
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED
                )
                if self._router._isShuttingDownTask in done:
                    _PPMsg(f'SHUTDOWN', msg)
                    reply = Missing
                elif fut in done:
                    reply = fut.result()
                else:
                    _PPMsg(f'TIMED OUT', msg)
                    reply = Missing
            except asyncio.CancelledError:
                _PPMsg(f'CANCELLED', msg)
                reply = Missing
            self._futureAndSubjectsByReplyId.pop(msg._msgId, None)
            return reply
        else:
            # async send
            _PPMsg('send', msg)
            self._router._route(msg)
            return None

    async def _deliver(self, msg):
        if (futAndSubjects := self._futureAndSubjectsByReplyId.pop(msg._replyId, Missing)) is not Missing:
            fut, subjects = futAndSubjects
            if msg.subject in subjects:
                # we have a future waiting for this reply
                if fut.done():
                    # is this possible? OPEN: log a warning that the apparently impossible has happened
                    pass
                else:
                    # we have the reply in time so pass it to the future
                    _PPMsg(f'deliver reply', msg._msgId)
                    fut.set_result(msg)
                return None

        if self._msgArrivedFn:
            # no future waiting for this reply so just pass it to the handler
            _PPMsg(f'deliver msg', msg._msgId)
            try:
                res = await self._msgArrivedFn(msg)
                if res is None:
                    pass
                else:
                    if isinstance(res, str): res = [str]
                    handled = False
                    for instruction in res:
                        if instruction == VLM.IGNORE_UNHANDLED_REPLIES:
                            if msg.isReply:
                                handled = True
                                break
                        elif instruction == VLM.HANDLE_PING:
                            if msg.subject == VLM.PING and not msg.isReply:
                                await self.send(msg.reply(None))
                                handled = True
                        elif instruction == VLM.HANDLE_SHUTDOWN:
                            if msg.subject == VLM.SHUTDOWN and not msg.isReply:
                                await self.shutdown()
                                handled = True
                        elif instruction == VLM.HANDLE_DOES_NOT_UNDERSTAND:
                            if msg.subject == VLM.DOES_NOT_UNDERSTAND:
                                handled = True
                            else:
                                _PPMsg(f'UNHANDLED SUBJECT', msg)
                                await self.send(msg.reply(msg.subject, subject=VLM.DOES_NOT_UNDERSTAND))
                                handled = True
                        else:
                            raise SyntaxError(f'Unknown instruction "{instruction}".')
                    if not handled:
                        _PPMsg(f'UNHANDLED SUBJECT', msg)
            except ExitMessageHandler as ex:
                pass
        else:
            if msg.subject == VLM.MSG_NOT_DELIVERED:
                # don't get into a loop of undeliverable messages
                pass
            else:
                # no handler so reply it wasn't delivered
                _PPMsg(f'undeliverable', msg._msgId)
                await self.send(msg.reply(msg.toAddr, subject=VLM.MSG_NOT_DELIVERED))

    def __del__(self):
        # clean up any pending futures
        for fut in self._futureAndSubjectsByReplyId.values():
            if not fut.done():
                fut.set_result(Missing)
        # tell router
        self._router._dropInboxFor(self.addr.connectionId)

    def getDirectoryAddr(self):
        return self._router._getDirectoryAddr()

    async def shutdown(self):
        self._router.shutdown()
        await until(self._router.hasShutdown)



# **********************************************************************************************************************
# Router
# **********************************************************************************************************************

class Router:

    __slots__ = (
        '_name',
        '_connectionById',
        '_inboxById',                   # each connection's queue
        '_connectionIdSeed',
        '_routerId',
        '_endpointId',
        '_sbMachine',                   # machine (ipc) socket bundle
        '_sbHub',                       # hub directory (ipc) socket bundle
        '_sbNetwork',                   # network (tcp) socket bundle
        '_directory',
        '_canRunLocalHubDirectory',
        '_taskListChanged',
        '_isShuttingDown',              # an Event signalling that the router is shutting down
        '_isShuttingDownTask',          # a task that waits for the isShuttingDown event that connections can use to timeout
        '_hasShutdown',                 # an Event signalling that the router has shutdown
        '_scheduledCallbacksByFnId',
        # _pipeByEndpointAndRouterId    # for a single hop - if not here then use the following
        # _pipeByEndpointId
    )

    # PUBLIC API

    def __init__(self, mode=VLM.MACHINE_MODE, canRunLocalHubDirectory=True, name=Missing):
        if mode not in (VLM.LOCAL_MODE, VLM.MACHINE_MODE, VLM.NETWORK_MODE):
            raise ValueError(f'Unknown router mode "{mode}".')

        self._name = name

        self._connectionById = weakref.WeakValueDictionary()
        self._inboxById = {}
        self._connectionIdSeed = itertools.count(_FIRST_CONNECTION_ID)

        self._routerId = None
        self._endpointId = None
        self._sbMachine = Missing
        self._sbHub = Missing
        self._sbNetwork = Missing
        self._canRunLocalHubDirectory = canRunLocalHubDirectory

        self._taskListChanged = asyncio.Event()
        self._isShuttingDown = asyncio.Event()
        self._isShuttingDownTask = taskOnEvent(self._isShuttingDown)
        self._hasShutdown = asyncio.Event()
        self._scheduledCallbacksByFnId = {}


        # figure the routerId and listen on a (local) socket
        if mode in (VLM.MACHINE_MODE, VLM.NETWORK_MODE):
            self._sbMachine = _SocketBundle(self)
            self._routerId = self._sbMachine.listen(next(_routerIdSeed), _ipcUrl, _MAX_IPC_LISTEN_ATTEMPTS)

            # initial attempt to connect to machine hub directory
            self._checkMachineHubConnection()

            # schedule periodic check of machine hub directory connection
            self.scheduleCallback(self._checkMachineHubConnection, every=1000 + random.randint(-100, 200))

        if mode == VLM.NETWORK_MODE:
            # OPEN: only needs to listen if configured to do so or a connection wants to advertise itself on the
            #       network - can create outgoing socket on demand when first message sent
            self._endpointId = self._sbNetwork.listen(30000)
            # - additionally will attempt to find network hub directories
            # - will listen for remote machine peers only if an agent advertises itself on a network hub directory
            # networkHubDirectoryPorts = [30000, 30001, 30002] - attempts to listen on port every x milliseconds
            #   - adds network hub directory to machine hub directory and own directory and forwards messages from the port
            #     to the network hub directory
            # isIntraMachineRouter - allows forwarding of messages between other machine routers and network routers

        if name is Missing: self._name = f'router_{self._routerId}'
        # OPEN: pass relevant network parameters here, e.g. network hub addresses etc
        self._directory = Directory(self, autoDrop=False)   # OPEN: False for dev so needs setting elsewhere

        asyncio.create_task(self._mainLoop())


    def newConnection(self, fn=Missing):
        return self._newConnection(next(self._connectionIdSeed), fn)

    def shutdown(self):
        self._connectionById = {}
        self._isShuttingDown.set()

    @property
    def hasShutdown(self):
        return self._hasShutdown

    def scheduleCallback(self, fn, every=Missing, after=Missing):
        # OPEN: move this to the routers main loop so can be cancelled cleanly on shutdown and make debugging easier
        # OPEN: implement after
        fnId = id(fn)
        if fnId in self._scheduledCallbacksByFnId:
            raise ProgrammerError(f'Callback function {fn} is already scheduled.')
        async def callbackLoop():
            try:
                while not self._isShuttingDown.is_set():
                    await until(timeout=every)
                    fn()
            except asyncio.CancelledError:
                pass
        task = asyncio.create_task(callbackLoop())
        self._scheduledCallbacksByFnId[fnId] = task

    def unscheduleCallback(self, fn):
        if fnId := id(fn) in self._scheduledCallbacksByFnId:
            self._scheduledCallbacksByFnId.pop(fnId).cancel()


    # LOCAL CONNECTION MANAGEMENT

    def _newConnection(self, connectionId, fn):
        c = Connection(self, Addr(self._endpointId, self._routerId, connectionId), fn)
        assert connectionId not in self._connectionById
        self._connectionById[connectionId] = c
        self._inboxById[connectionId] = Queue()
        self._taskListChanged.set()
        return c

    def _getDirectoryAddr(self):
        return Addr(None, self._routerId, _DIRECTORY_CONNECTION_ID)

    def _dropInboxFor(self, connectionId):
        self._inboxById.pop(connectionId, None)
        self._taskListChanged.set()


    def _cancelConnectingToLocal(self, routerId):
        if (accumulatedMsgs := self._accumulatedMsgsByRouterId.get(routerId, Missing)) is Missing: return
        self._accumulatedMsgsByRouterId.pop(routerId, None)
        self._taskListChanged.set()
        for msg in accumulatedMsgs.msgs():
            if msg.subject == VLM.MSG_NOT_DELIVERED:
                # don't get into a loop of undeliverable messages
                pass
            else:
                reply = msg.reply(msg.toAddr, subject=VLM.MSG_NOT_DELIVERED)
                reply._msgId = -1
                _PPMsg(f'unroutable', msg._msgId)
                self._route(reply)

    def _checkMachineHubConnection(self):
        # OPEN: implement
        pass
        # if _MACHINE_HUB_ROUTER_ID not in self._sbHub._pipesByRemoteId:
        #     if not self._sHubIn and self._canRunLocalHubDirectory:
        #         # try to become the machine hub directory
        #         try:
        #             s = pynng.Pair1(polyamorous=True)
        #             s.listen(_ipcUrl(_MACHINE_HUB_ROUTER_ID))
        #             s.add_post_pipe_connect_cb(self._onHubInConnect)
        #             s.add_post_pipe_remove_cb(self._onHubInDisconnect)
        #             self._sHubIn = s
        #         except pynng.exceptions.AddressInUse as ex:
        #             pass
        #     if not self._sHubIn and not self._sHubOut:
        #         # we do not host the machine hub directory try to connect to it
        #         _sHubOut = pynng.Pair1(polyamorous=True)
        #         _sHubOut.add_post_pipe_connect_cb(self._sHubOutPostConnectCb)
        #         _sHubOut.add_post_pipe_remove_cb(self._sHubOutPostRemoveCb)
        #         _sHubOut.dial(_ipcUrl(_MACHINE_HUB_ROUTER_ID), block=False)


    # ROUTING

    def _route(self, msg):
        endpointId, routerId, cId = msg.toAddr
        if not endpointId:
            if routerId == self._routerId:
                inbox = self._inboxById.get(cId, Missing)
                if inbox:
                    _PPMsg(f'route', f'connId: {cId}, msgId: {msg._msgId}')
                    pushBack(inbox, msg)
                else:
                    if msg.subject == VLM.MSG_NOT_DELIVERED:
                        # don't get into a loop of undeliverable messages
                        pass
                    else:
                        reply = msg.reply(msg.toAddr, subject=VLM.MSG_NOT_DELIVERED)
                        reply._msgId = -1
                        _PPMsg(f'unroutable', msg._msgId)
                        self._route(reply)
            else:
                self._sbMachine._route(routerId, msg)
        else:
            self._sbNetwork.route(endpointId, msg)


    # MAIN LOOP

    async def _mainLoop(self):
        # To prevent starvation we watch tasks fairly by moving a task that has just been processed to the bottom of the
        # list thus silent tasks bubble to the top. This is mildly wasteful since silent tasks need to, presumably, be 
        # checked each loop, but it does ensure that busy tasks don't dominate less busy tasks.
        taskList = {
            self._isShuttingDownTask: _Details(_SHUTDOWN_TRIGGERED, None),
            taskOnEvent(self._taskListChanged): _Details(_TASKLIST_CHANGED, None),
        }
        running = True
        pending = []
        while running:
            done, pending = await until(taskList.keys(), return_when=asyncio.FIRST_COMPLETED)

            # process done tasks (always just one?)
            for task in done:
                details = taskList.pop(task)                                           # take task from the list
                _PPMsg(f'main', f'{self._name} - {_eventPPNameById[details.type]}')

                if details.type == _MSG_ARRIVED:
                    cId = details.args
                    msg = task.result()
                    if (conn := self._connectionById.get(cId, Missing)) is not Missing:
                        inbox = self._inboxById[cId]
                        # we need to schedule a new task here rather than await otherwise we block processing other events
                        asyncio.create_task(conn._deliver(msg))
                        taskList[asyncio.create_task(inbox.get())] = details           # add task to bottom of list

                elif details.type == _SOCK_RECV:
                    incoming = task.result()
                    sb = details.args
                    pipe = incoming.pipe
                    if pipe.id not in sb._remoteIdByPipeId:
                        # first message on this pipe is the remoteId
                        remoteId = sys.intern(incoming.bytes.decode())
                        if (pipeByPipeId := sb._pipesByRemoteId.get(remoteId, Missing)) is Missing:
                            _PPMsg('main::ipc_recv', f'{self._name} received remoteId {remoteId} for channel {pipe.url}')
                            pipeByPipeId = sb._pipesByRemoteId[remoteId] = {}
                        else:
                            _PPMsg('main::ipc_recv', f'{self._name} - WARNING: already connected to {remoteId} - adding additional connection')
                            sb._remoteIdsWithExcessPipes.add(remoteId)
                        sb._remoteIdByPipeId[pipe.id] = remoteId
                        pipeByPipeId[pipe.id] = pipe
                        if (accumulatedMsgs := sb._accumulatedMsgsByRemoteId.pop(remoteId, Missing)) is not Missing:
                            for msg in accumulatedMsgs.msgs:
                                _PPMsg('main::ipc_recv', f'{self._name} - sending accumulated {msg}')
                                cosend(pipe, _msgAsBytes(msg))
                    else:
                        msg = _msgFromBytes(incoming.bytes)
                        self._route(msg)
                    taskList[corecv(sb.sock)] = details                                 # add task to bottom of list

                elif details.type == _CONNECTION_ATTEMPT_TIMEOUT:
                    # OPEN: cancel the dialer if it is still trying to connect, return unroutable messages to sender
                    raise NotYetImplemented('_CONNECTION_ATTEMPT_TIMEOUT')
                    # _accumulatedMsgsByRouterId

                elif details.type == _TIMER:
                    fnId = details.args
                    raise NotYetImplemented('_TIMER')

                elif details.type == _TASKLIST_CHANGED:
                    # remove old tasks that are no longer needed
                    tasksToRemove = []
                    for t, m in taskList.items():
                        if m.type == _MSG_ARRIVED and m.args not in self._connectionById:
                            tasksToRemove.append(t)   # drop closed connections
                    for t in tasksToRemove:
                        # _PPMsg(f'dropping', f'{tasksToRemove[t]}')
                        t.cancel('no longer needed')
                        await until(timeout=0)
                        # t.uncancel()    # "in cases when suppressing asyncio.CancelledError is truly desired, it is necessary to also call uncancel()"
                        taskList.pop(t)
                    await asyncio.gather(*tasksToRemove, return_exceptions=True)

                    # add any inbox tasks that are needed
                    for cId, conn in self._connectionById.items():
                        if _Details(_MSG_ARRIVED, cId) not in taskList.values():
                            taskList[coPopFront(self._inboxById[cId])] = _Details(_MSG_ARRIVED, cId)
                            _PPMsg(f'main', f'{self._name} - added MSG_ARRIVED task for connId: {cId}')

                    # add any socket tasks that are needed
                    if self._sbMachine and _Details(_SOCK_RECV, self._sbMachine) not in taskList.values():
                        taskList[corecv(self._sbMachine.sock)] = _Details(_SOCK_RECV, self._sbMachine)
                        _PPMsg(f'main', f'{self._name} - added machine SOCK_RECV task')

                    if self._sbHub and _Details(_SOCK_RECV, self._sbHub) not in taskList.values():
                        taskList[corecv(self._sbHub.sock)] = _Details(_SOCK_RECV, self._sbHub)
                        _PPMsg(f'main', f'{self._name} - added hub SOCK_RECV task')

                    if self._sbNetwork and _Details(_SOCK_RECV, self._sbNetwork) not in taskList.values():
                        taskList[corecv(self._sbNetwork.sock)] = _Details(_SOCK_RECV, self._sbNetwork)
                        _PPMsg(f'main', f'{self._name} - added network SOCK_RECV task')


                    # scheduled callbacks
                    # for fnId, cb in self._scheduledCallbacksByFnId.items():
                    #     if (_TIMER, fnId) not in taskList.values():

                    self._taskListChanged.clear()
                    taskList[taskOnEvent(self._taskListChanged)] = details              # add task to bottom of list

                elif details.type == _SHUTDOWN_TRIGGERED:
                    running = False
                    break

                else:
                    raise ProgrammerError(f'Unknown monitor type "{details.type}".')

        for t in pending:
            t.cancel()
            await until(timeout=0)
        for t in taskList.keys():
            t.cancel()
            await until(timeout=0)
        if self._sbMachine:
            self._sbMachine.close()
        if self._sbNetwork:
            self._sbNetwork.close()
        self._hasShutdown.set()
        _PPMsg('shutdown', self._name)


    # DISPLAY

    def __str__(self):
        return f'Router<{self._name}::{self._routerId}>'



class _SocketBundle:
    __slots__ = (
        '_router',
        '_remoteId',
        '_urlFn',
        'sock',
        '_pipesByRemoteId',             # pipe by pipeId by routerId - so we know which pipe to send a msg down
        '_remoteIdByPipeId',            # so we know which remote a msg has come from - not strictly required except for validating a from address?
        '_remoteIdsWithExcessPipes',
        '_dialerByRemoteId',            # so we can cancel dialing if we need to
        '_accumulatedMsgsByRemoteId',   # to be checked periodically for connection, reply with unroutable on time out
    )


    # LIFECYCLE

    def __init__(self, router):
        self._router = router
        self._remoteId = Missing
        self._urlFn = Missing
        self.sock = Missing
        self._pipesByRemoteId = {}
        self._remoteIdByPipeId = {}
        self._remoteIdsWithExcessPipes = set()
        self._dialerByRemoteId = {}
        self._accumulatedMsgsByRemoteId = {}

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = Missing


    # CONNECTION MANAGEMENT

    def listen(self, remoteIdSeed, urlFn, maxAttempts):
        # OPEN: figure out how to recover from AddressInUse properly rather than just trying a new id - in the same
        #       process in ipc mode it breaks the ability of a prior listening socket to be connected to (I suppose the
        #       listener pointer is changed of something?)
        self._urlFn = urlFn
        self._remoteId = self._urlFn(remoteIdSeed)
        i = 0
        while i < maxAttempts:
            self.sock = pynng.Pair1(polyamorous=True)
            try:
                self.sock.listen(self._remoteId)
                self.sock.add_post_pipe_connect_cb(self._onConnect)
                self.sock.add_post_pipe_remove_cb(self._onDisconnect)
                _PPMsg('listening', f'{self._router._name or str(self._remoteId)} - {self._remoteId}')
                break
            except pynng.exceptions.AddressInUse as ex:
                for l in self.sock.listeners:
                    l.close()
                self.sock.close()
                remoteIdSeed += 1
                self._remoteId = self._urlFn(remoteIdSeed)
                i += 1
        if i >= maxAttempts:
            raise RuntimeError(f'Unable to find a free ipc address.')
        self._router._taskListChanged.set()
        return self._remoteId

    def _dial(self, remoteId, timeout):
        assert remoteId not in self._accumulatedMsgsByRemoteId
        accumulatedMsgs = self._accumulatedMsgsByRemoteId[remoteId] = _AccumulatedMessages(monotonicTimeMs() + timeout)
        self._dialerByRemoteId[remoteId] = dial(self.sock, remoteId, block=False)
        _PPMsg('dialing_router', f'{self._router._name} dialing {remoteId}')
        return accumulatedMsgs

    def _completeConnectingToLocal(self, msgsAwaitingConnection):
        # send all the queued messages awaiting connection to the newly connected router
        for msg in msgsAwaitingConnection.msgs():
            self._route(msg)
        self._accumulatedMsgsByRemoteId.pop(msgsAwaitingConnection.routerId, None)
        self._router._taskListChanged.set()


    # SOCKET CALLBACKS

    def _onConnect(self, pipe):
        print(self._router._name)
        _PPMsg('connect', f'{self._router._name} - {pipeConnectionType(pipe)} on channel {pipe.url}')
        try:
            # send my router id to the remote peer as the first message on this pipe
            # comes in on a different thread so can't use event loop on main thread
            send(pipe, str(self._remoteId).encode(), block=False)
        except Exception as ex:
            _PPMsg('router_connect', f'#err {self._router._name} exception - {repr(ex)}')

    def _onDisconnect(self, pipe):
        remoteId = self._remoteIdByPipeId.pop(pipe.id, Missing)
        if remoteId:
            if (pipeByPipeId := self._pipesByRemoteId.get(remoteId, Missing)) is not Missing:
                pipeByPipeId.pop(pipe.id, None)
            _PPMsg('router_disconnect', f'{self._router._name} <{remoteId}> - {pipeConnectionType(pipe)} on channel <{pipe.url}>')
        else:
            _PPMsg('router_disconnect', f'{self._router._name} - {pipeConnectionType(pipe)} on channel {pipe.url}')


    # ROUTING

    def _route(self, remoteId, msg):
        if (pipeByPipeId := self._pipesByRemoteId.get(remoteId, Missing)) is Missing:
            if (accumulatedMsgs := self._accumulatedMsgsByRemoteId.get(remoteId, Missing)) is Missing:
                accumulatedMsgs = self._dial(remoteId, _DEFAULT_LOCAL_CONNECTION_TIMESOUT)
            accumulatedMsgs.queueMsg(msg)
        else:
            pipe = firstValue(pipeByPipeId)
            cosend(pipe, _msgAsBytes(msg))  # we might be able to await this instead but not sure we gain much



# **********************************************************************************************************************
# Directory
# **********************************************************************************************************************

class Directory:
    # OPEN: add security so agents can only add / remove their own entries and see only what they are allowed to see,
    #       but what about telling a directory that a connection didn't get delivered
    __slots__ = (
        '_conn',
        '_entries',                 # [Entry]
        '_potentiallyStale',        # set() of addr we haven't heard from in a while
        '_heartbeatEntriesInterval',
    )

    def __init__(self, router, autoDrop=True, heartbeatEntriesTimeout=Missing):
        if router._connectionById.get(_DIRECTORY_CONNECTION_ID, Missing) is not Missing:
            raise RuntimeError('A Directory already exists on this router')
        self._conn = router._newConnection(_DIRECTORY_CONNECTION_ID, self.msgArrived)
        self._heartbeatEntriesInterval = _DEFAULT_HEARTBEAT_ENTRIES_INTERVAL if heartbeatEntriesTimeout is Missing else heartbeatEntriesTimeout
        if autoDrop:
            router.scheduleCallback(self._heartbeatEntries, every=self._heartbeatEntriesInterval)
        self._entries = []
        self._potentiallyStale = set()

    async def msgArrived(self, msg):
        self._potentiallyStale.discard(msg.fromAddr)

        if msg.subject == VLM.REGISTER_ENTRY:
            addr, service, params, vnets, perms = msg.contents
            for a, s, p, _, _ in self._entries:
                if a == addr and s == service and p == params:
                    await self._conn.send( msg.reply(True) )
                    return
            self._entries.append( msg.contents )
            await self._conn.send(msg.reply(True))

        elif msg.subject == VLM.UNREGISTER_ENTRY:
            entry = msg.contents
            self._entries = [e for e in self._entries if e != entry]
            await self._conn.send(msg.reply(True))

        elif msg.subject == VLM.UNREGISTER_ADDR:
            addr = msg.contents
            self._entries = [e for e in self._entries if e.addr != addr]
            await self._conn.send(msg.reply(True))

        elif msg.subject == VLM.GET_ENTRIES:
            if msg.contents:
                await self._conn.send(msg.reply([e for e in self._entries if e.service == msg.contents]))
            else:
                await self._conn.send(msg.reply(self._entries))

        else:
            return [VLM.HANDLE_PING, VLM.HANDLE_DOES_NOT_UNDERSTAND]

    def _heartbeatEntries(self):
        self._entries = [entry for entry in self._entries if entry.addr not in self._potentiallyStale]
        self._potentiallyStale = set([entry.addr for entry in self._entries])
        for addr in self._potentiallyStale:
            asyncio.create_task(self._conn.send(Msg(addr, VLM.PING, None)))



# **********************************************************************************************************************
# Serialization
# **********************************************************************************************************************

def _msgAsBytes(msg):
    bytes = io.BytesIO()
    simpleion.dump('1', bytes, binary=True)
    simpleion.dump(msg.fromAddr.endpointId, bytes, binary=True)         # string or None
    simpleion.dump(msg.fromAddr.routerId, bytes, binary=True)           # string
    simpleion.dump(msg.fromAddr.connectionId, bytes, binary=True)       # int
    simpleion.dump(msg.toAddr.endpointId, bytes, binary=True)            # string or None
    simpleion.dump(msg.toAddr.routerId, bytes, binary=True)             # string
    simpleion.dump(msg.toAddr.connectionId, bytes, binary=True)         # int
    simpleion.dump(msg.subject, bytes, binary=True)                     # string
    simpleion.dump(msg._msgId, bytes, binary=True)                      # int
    simpleion.dump(msg._replyId, bytes, binary=True)                    # int or None
    simpleion.dump(msg.contents, bytes, binary=True)                    # any ION serializable
    simpleion.dump(msg.meta, bytes, binary=True)                        # dict
    return bytes.getvalue()

def _msgFromBytes(bytes):
    try:
        values = simpleion.load(io.BytesIO(bytes), single_value=False)
        schema, fromEndpointId, fromRouterId, fromConnId, toEndpointId, toRouterId, toConnId, subject, _msgId, _replyId, contents, meta = values
        assert _toPy(schema) == '1'
        msg = Msg(Addr(_toPy(toEndpointId), _toPy(toRouterId), _toPy(toConnId)), _toPy(subject), _toPy(contents))
        msg.fromAddr = Addr(_toPy(fromEndpointId), _toPy(fromRouterId), _toPy(fromConnId))
        msg._msgId = _toPy(_msgId)
        msg._replyId = _toPy(_replyId)
        msg.meta = _toPy(meta)
        # OPEN: assert stream at end
        return msg
    except Exception as ex:
        _PPMsg('_msgFromBytes error', repr(ex))
        raise

def _toPy(x):
    if isinstance(x, simpleion.IonPyInt):
        return int(x)
    elif isinstance(x, simpleion.IonPyFloat):
        return float(x)
    elif isinstance(x, simpleion.IonPyBool):
        return bool(x)
    elif isinstance(x, simpleion.IonPyText):
        return str(x)
    elif isinstance(x, simpleion.IonPyList):
        return [_toPy(y) for y in x]
    elif isinstance(x, simpleion.IonPyDict):
        return {_toPy(k):_toPy(v) for k, v in x.items()}
    elif isinstance(x, simpleion.IonPyNull):
        return None
    elif isinstance(x, (str, int, float, bool)):
        _PPMsg('_toPy', f'WARNING: primitive type "{type(x)}" passed through unchanged.')
        return x
    else:
        raise ProgrammerError(f'Unknown ION type "{type(x)}".')


# **********************************************************************************************************************
# Utils
# **********************************************************************************************************************

def _ipcUrl(id):
    return sys.intern(f'ipc:///tmp/router_{id}')

def _tcpAddr(ip, port):
    if ip.upper() == 'LOCALHOST':
        return sys.intern(f'tcp://127.0.0.1:{port}')
    else:
        return sys.intern(f'tcp://{ip}:{port}')

class _AccumulatedMessages:
    __slots__ = ('msgs', '_expiryTimeMs', '_maxQueue')

    def __init__(self, timeout, maxQueue=Missing):
        self.msgs = []
        self._expiryTimeMs = monotonicTimeMs() + timeout
        self._maxQueue = maxQueue

    def queueMsg(self, msg):
        self.msgs.append(msg)

    @property
    def hasExpired(self):
        return self._expiryTimeMs < monotonicTimeMs() or (self._maxQueue and len(self.msgs) > self._maxQueue)
