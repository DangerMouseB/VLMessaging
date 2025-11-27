# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************


# Python imports
import itertools, logging, pynng, asyncio, weakref, collections, io, os, random
from amazon.ion import simpleion

# coppertop imports
from coppertop.utils import Missing, NotYetImplemented, ProgrammerError

# local imports
from vlmessaging.utils import until, monotonicTimeMs, adequeue, queue, arecv, Queue, asend, dial, send, \
    pipeConnectionType
from vlmessaging import _constants as VLM


_logger = logging.getLogger(__name__)
random.seed(int.from_bytes(os.urandom(8), 'big'))


_DIRECTORY_CONNECTION_ID = 1
_FIRST_CONNECTION_ID = _DIRECTORY_CONNECTION_ID + 1
_MACHINE_HUB_ROUTER_ID = 0
_MAX_IPC_LISTEN_ATTEMPTS = 1000
_DEFAULT_HEARTBEAT_ENTRIES_INTERVAL = 10_000


Monitor = collections.namedtuple('Monitor', ('type', 'args'))
_INBOX_EVENT = 1
_IPC_EVENT = 2
_TCP_EVENT = 3
_TIMER_EVENT = 4
_SHUTDOWN_EVENT = 5
_AWAITING_CONNECTION_TIMER_EVENT = 6
_DEFAULT_LOCAL_CONNECTION_TIMESOUT = 2000

class ExitMessageHandler(Exception): pass


# **********************************************************************************************************************
# Public Structs
# **********************************************************************************************************************

Addr = collections.namedtuple('Addr', ('machineId', 'routerId', 'connectionId'))
def Addr__str__(self):
    if self.routerId is None:
        return f'<{self.connectionId}>'
    elif self.machineId is None:
        return f'<{self.routerId}:{self.connectionId}>'
    else:
        return f'<{self.machineId}:{self.routerId}:{self.connectionId}>'
Addr.__str__ = Addr__str__


Entry = collections.namedtuple('Entry', ('addr', 'service', 'params', 'vnets', 'perms'))


Perm =  collections.namedtuple('Perm', ('domain', 'permId'))


class Msg:

    __slots__ = ('fromAddr', 'toAddr', 'subject', '_msgId', '_replyId', 'contents', 'meta')

    def __init__(self, toAddr, subject, contents):
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

    def __init__(self, router, connectionId, fn):
        self._router = router
        self._msgArrivedFn = fn
        self._futureAndSubjectsByReplyId = {}
        self._msgIdSeed = itertools.count(1)
        self.addr = Addr(None, router._routerId, connectionId)

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
        await self._router.shutdown()



# **********************************************************************************************************************
# Router
# **********************************************************************************************************************

class Router:

    # NoteToSelf: can close dialers

    __slots__ = (
        '_routerId',
        '_name',
        '_connectionIdSeed',
        '_inboxById',               # each connection's queue
        '_connectionById',
        '_refreshTasksToMonitor',
        '_isShuttingDown',          # an Event signalling that the router is shutting down
        '_isShuttingDownTask',      # a task that waits for the isShuttingDown event that connections can use to timeout
        '_hasShutdown',             # an Event signalling that the router has shutdown
        '_sMachine',                  # socket for connections with other routers on this machine
        '_sHubIn',                  # socket for acting as the hub directory
        '_sHubOut',                 # socket for connecting to the hub directory - can be dropped if we become the hub directory
        '_pipeByPipeId',            # when we get a new pipe we store it here
        '_pipeByRouterId',          # so we know which pipe to send a msg down
        '_routerIdByPipeId',        # so we know which router a msg has come from - not strictly required except for validating a from address?
        '_directory',
        '_canRunLocalHubDirectory',
        '_scheduledCallbacksByFnId',
        '_queuedMsgByRouterId',     # to be checked periodically for connection, reply with unroutable on time out
        '_dialerByAddress',        
        # _pipeByMachineAndRouterId     # for a single hop - if not here then use the following
        # _pipeByMachineId              # for a two hop - machine id doesn't need to be a machine id could just be an IP

    )

    # PUBLIC API

    def __init__(self, mode=VLM.MACHINE_MODE, canRunLocalHubDirectory=True, name=Missing):
        if mode not in (VLM.LOCAL_MODE, VLM.MACHINE_MODE, VLM.NETWORK_MODE):
            raise ValueError(f'Unknown router mode "{mode}".')

        self._connectionById, self._inboxById, self._connectionIdSeed = weakref.WeakValueDictionary(), {}, itertools.count(_FIRST_CONNECTION_ID)
        self._refreshTasksToMonitor = False
        self._isShuttingDown = asyncio.Event()
        self._hasShutdown = asyncio.Event()
        self._isShuttingDownTask = asyncio.create_task(self._isShuttingDown.wait())

        self._sMachine, self._sHubIn, self._sHubOut = Missing, Missing, Missing
        self._pipeByPipeId, self._pipeByRouterId, self._routerIdByPipeId = {}, {}, {}
        self._canRunLocalHubDirectory = canRunLocalHubDirectory
        self._scheduledCallbacksByFnId = {}
        self._queuedMsgByRouterId = {}
        self._dialerByAddress = {}
        self._routerId = 0
        self._name = name

        # figure the routerId and listen on a (local) socket
        if mode in (VLM.MACHINE_MODE, VLM.NETWORK_MODE):
            # OPEN: random number instead? any advantages or security concern about using pid?
            self._listenForMachine(os.getpid())

            # initial attempt to connect to machine hub directory
            self._checkMachineHubConnection()

            # schedule periodic check of machine hub directory connection
            self.scheduleCallback(self._checkMachineHubConnection, every=1000 + random.randint(-100, 200))

        if mode == VLM.NETWORK_MODE:
            # - additionally will attempt to find network hub directories
            # - will listen for remote machine peers only if an agent advertises itself on a network hub directory
            # networkHubDirectoryPorts = [30000, 30001, 30002] - attempts to listen on port every x milliseconds
            #   - adds network hub directory to machine hub directory and own directory and forwards messages from the port
            #     to the network hub directory
            # isIntraMachineRouter - allows forwarding of messages between other machine routers and network routers
            raise NotYetImplemented('NETWORK_MODE')

        if name is Missing: self._name = str(self._routerId)
        self._directory = Directory(self, autoDrop=False)   # OPEN: False for dev so needs setting elsewhere

        asyncio.create_task(self._mainLoop())


    def newConnection(self, fn=Missing):
        return self._newConnection(next(self._connectionIdSeed), fn)

    async def shutdown(self):
        self._connectionById = {}
        self._isShuttingDown.set()
        await until(timeout=10)  # do this here so the client doesn't have to - annoyingly we can't loop until done
        self._hasShutdown.set()

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
        c = Connection(self, connectionId, fn)
        assert connectionId not in self._connectionById
        self._connectionById[connectionId] = c
        self._inboxById[connectionId] = Queue()
        self._refreshTasksToMonitor = True
        return c

    def _getDirectoryAddr(self):
        return Addr(None, self._routerId, _DIRECTORY_CONNECTION_ID)

    def _dropInboxFor(self, connectionId):
        self._inboxById.pop(connectionId, None)
        self._refreshTasksToMonitor = True


    # MACHINE CONNECTION MANAGEMENT

    def _listenForMachine(self, routerId):
        # create and setup _sMachine socket
        self._routerId = os.getpid()
        self._sMachine = pynng.Pair1(polyamorous=True)
        self._sMachine.add_post_pipe_connect_cb(self._onMachineConnect)
        self._sMachine.add_post_pipe_remove_cb(self._onMachineDisconnect)
        i = 0
        while i < _MAX_IPC_LISTEN_ATTEMPTS:
            try:
                self._sMachine.listen(_ipcAddr(self._routerId))
                _PPMsg('Listening', f'{self._name or str(self._routerId)} - {_ipcAddr(self._routerId)}')
                break
            except pynng.exceptions.AddressInUse as ex:
                self._routerId += 1
                i += 1
        if i >= _MAX_IPC_LISTEN_ATTEMPTS:
            raise RuntimeError(f'Unable to find a free ipc address.')

    def _startConnectingToLocal(self, routerId, timeout):
        queuedMsgs = self._queuedMsgByRouterId[routerId] = _MesagesAwaitingConnection(timeout)
        # self._refreshTasksToMonitor = True
        addr = _ipcAddr(routerId)
        self._dialerByAddress[addr] = dial(self._sMachine, addr, block=False)
        _PPMsg('DialingLocal', f'{self._name} dialing {addr}')
        return queuedMsgs

    def _completeConnectingToLocal(self, msgsAwaitingConnection):
        # send all the queued messages awaiting connection to the newly connected router
        for msg in msgsAwaitingConnection.msgs():
            self._route(msg)
        self._queuedMsgByRouterId.pop(msgsAwaitingConnection.routerId, None)
        self._refreshTasksToMonitor = True

    def _cancelConnectingToLocal(self, routerId):
        if (queuedMsgs := self._queuedMsgByRouterId.get(routerId, Missing)) is Missing: return
        self._queuedMsgByRouterId.pop(routerId, None)
        self._refreshTasksToMonitor = True
        for msg in queuedMsgs.msgs():
            if msg.subject == VLM.MSG_NOT_DELIVERED:
                # don't get into a loop of undeliverable messages
                pass
            else:
                reply = msg.reply(msg.toAddr, subject=VLM.MSG_NOT_DELIVERED)
                reply._msgId = -1
                _PPMsg(f'unroutable', msg._msgId)
                self._route(reply)

    def _checkMachineHubConnection(self):
        if not (hubPipe := self._pipeByRouterId.get(_MACHINE_HUB_ROUTER_ID, Missing)):
            if not self._sHubIn and self._canRunLocalHubDirectory:
                # try to become the machine hub directory
                try:
                    s = pynng.Pair1(polyamorous=True)
                    s.listen(_ipcAddr(_MACHINE_HUB_ROUTER_ID))
                    s.add_post_pipe_connect_cb(self._onHubInConnect)
                    s.add_post_pipe_remove_cb(self._onHubInDisconnect)
                    self._sHubIn = s
                except pynng.exceptions.AddressInUse as ex:
                    pass
            if not self._sHubIn and not self._sHubOut:
                # we do not host the machine hub directory try to connect to it
                _sHubOut = pynng.Pair1(polyamorous=True)
                _sHubOut.add_post_pipe_connect_cb(self._sHubOutPostConnectCb)
                _sHubOut.add_post_pipe_remove_cb(self._sHubOutPostRemoveCb)
                _sHubOut.dial(_ipcAddr(_MACHINE_HUB_ROUTER_ID), block=False)


    # MACHINE SOCKET CALLBACKS

    def _onMachineConnect(self, pipe):
        _PPMsg('_onMachineConnect', f'{self._name}')
        _PPMsg('_onMachineConnect', f'#1 {self._name} - {pipeConnectionType(pipe)} {_localPipeAddr(pipe)}')
        try:
            # send my router id to the remote peer as the first message on this pipe
            # comes in on a different thread so can't use event loop on main thread
            send(pipe, str(self._routerId).encode(), block=False)
        except Exception as ex:
            _PPMsg('_onMachineConnect', f'#2 {self._name} exception - {repr(ex)}')
        self._pipeByPipeId[pipe.id] = pipe
        self._refreshTasksToMonitor = True
        _PPMsg('_onMachineConnect', f'#3 {self._name}')

    def _onMachineDisconnect(self, pipe):
        _PPMsg('_onMachineDisconnect- 1', f'#1 {self._name} - {_localPipeAddr(pipe)}')
        routerId = self._routerIdByPipeId.pop(pipe.id, None)
        if routerId:
            self._pipeByRouterId.pop(routerId, None)
            _PPMsg('_onMachineDisconnect', f'#2 {self._name} - <{routerId}> aka <{_localPipeAddr(pipe)}>')
        else:
            _PPMsg('_onMachineDisconnect', f'#3 {self._name} - {_localPipeAddr(pipe)}')
        self._pipeByPipeId.pop(pipe.id, None)
        self._refreshTasksToMonitor = True

    def _onHubInConnect(self, pipe):
        addr = str(pipe.remote_address)
        if addr:
            routerId = int(addr.split('_')[-1])
            if routerId in self._pipeByRouterId:
                raise ProgrammerError(f'Router ID {routerId} already connected to IPC hub.')
            self._pipeByRouterId[routerId] = pipe
            self._refreshTasksToMonitor = True

    def _onHubInDisconnect(self, pipe):
        addr = str(pipe.remote_address)
        if addr:
            routerId = int(addr.split('_')[-1])
            self._pipeByRouterId.pop(routerId, None)
            self._refreshTasksToMonitor = True

    def _sHubOutPostConnectCb(self, pipe):
        addr = str(pipe.remote_address)
        if addr:
            routerId = int(addr.split('_')[-1])
            if routerId in self._pipeByRouterId:
                raise ProgrammerError(f'Router ID {routerId} already connected to IPC hub.')
            self._pipeByRouterId[routerId] = pipe
            self._refreshTasksToMonitor = True

    def _sHubOutPostRemoveCb(self, pipe):
        addr = str(pipe.remote_address)
        if addr:
            routerId = int(addr.split('_')[-1])
            self._pipeByRouterId.pop(routerId, None)
            self._refreshTasksToMonitor = True


    # ROUTING

    def _route(self, msg):
        machineId, routerId, connectionId = msg.toAddr
        if not machineId:
            if routerId == self._routerId:
                inbox = self._inboxById.get(connectionId, Missing)
                if inbox:
                    _PPMsg(f'route', msg._msgId)
                    queue(inbox, msg)
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
                ipcRouterPipe = self._pipeByRouterId.get(routerId, Missing)
                if ipcRouterPipe is Missing:
                    if (queuedMsgs := self._queuedMsgByRouterId.get(routerId, Missing)) is Missing:
                        queuedMsgs = self._startConnectingToLocal(routerId, _DEFAULT_LOCAL_CONNECTION_TIMESOUT)
                    queuedMsgs.queueMsg(msg)
                else:
                    asend(ipcRouterPipe, _msgAsBytes(msg))      # we might be able to await this instead but not sure we gain much
        else:
            # OPEN: handle inter-machine routing
            raise NotYetImplemented('inter-machine routing')


    # MAIN LOOP

    async def _mainLoop(self):
        # We keep a list of tasks waiting for events, i.e.:
        #   - message arriving in each connection's inbox
        #   - message arriving in each socket (local and remote)
        #   - shutdown event
        #   - timer events for scheduled callbacks
        #
        # To prevent starvation we schedule them fairly by moving a task that has just been processed to the end of the
        # list thus silent tasks bubble to the front. This is mildly wasteful since silent tasks need to be checked
        # each loop, but it does ensure that busy tasks don't dominate things.
        taskToMonitorMap = {self._isShuttingDownTask: Monitor(_SHUTDOWN_EVENT, None)}
        running = True
        pending = []
        _PPMsg(f'_mainLoop', f'{self._name}')
        while running:
            if self._refreshTasksToMonitor:
                # remove old tasks that are no longer needed
                tasksToRemove = []
                for t, m in taskToMonitorMap.items():
                    if m.type == _INBOX_EVENT and m.args not in self._connectionById: tasksToRemove.append(t)   # drop closed connections
                for t in tasksToRemove:
                    # _PPMsg(f'dropping', f'{tasksToRemove[t]}')
                    t.cancel('no longer needed')
                    await until(timeout=0)
                    # t.uncancel()    # "in cases when suppressing asyncio.CancelledError is truly desired, it is necessary to also call uncancel()"
                    taskToMonitorMap.pop(t)
                await asyncio.gather(*tasksToRemove, return_exceptions=True)

                # add new tasks that are needed
                # inboxes
                for cId, conn in self._connectionById.items():
                    if Monitor(_INBOX_EVENT, cId) not in taskToMonitorMap.values():
                        taskToMonitorMap[adequeue(self._inboxById[cId])] = Monitor(_INBOX_EVENT, cId)
                        _PPMsg(f'monitoring', f'{self._name} - {Monitor(_INBOX_EVENT, cId)}')

                # ipc sockets
                if self._sMachine and Monitor(_IPC_EVENT, 0) not in taskToMonitorMap.values():
                    taskToMonitorMap[arecv(self._sMachine)] = Monitor(_IPC_EVENT, 0)
                    _PPMsg(f'monitoring', f'{self._name} - {Monitor(_IPC_EVENT, 0)}')

                # connecting ipc sockets


                # tcp sockets


                # connecting sockets


                # scheduled callbacks
                # for fnId, cb in self._scheduledCallbacksByFnId.items():
                #     if (_TIMER_EVENT, fnId) not in taskToMonitorMap.values():
                #         taskToMonitorMap[asyncio.create_task(self._pipeByRouterId[routerId].get())] = Monitor(_TIMER_EVENT, fnId)  # add any new pic pipes

                self._refreshTasksToMonitor = False

            # wait for a task to complete
            _PPMsg(f'mainloop', f'{self._name} - awaiting tasks')
            done, pending = await asyncio.wait(taskToMonitorMap.keys(), return_when=asyncio.FIRST_COMPLETED)
            _PPMsg(f'mainloop', f'{self._name} - got {len(done)}')

            # process done tasks (always just one?)
            for task in done:
                # pull the done task from the queue
                m = taskToMonitorMap.pop(task)
                if m.type == _SHUTDOWN_EVENT:
                    running = False
                    break
                elif m.type == _INBOX_EVENT:
                    cId = m.args
                    msg = task.result()
                    if (conn := self._connectionById.get(cId, Missing)) is not Missing:
                        inbox = self._inboxById[cId]
                        # we need to schedule a new task here rather than await otherwise we block processing other events
                        asyncio.create_task(conn._deliver(msg))
                        taskToMonitorMap[asyncio.create_task(inbox.get())] = m              # add new task to end of queue
                elif m.type == _IPC_EVENT:
                    _PPMsg('IPC_EVENT', f'')
                    msg = task.result()
                    pipeId = msg.pipe.id
                    routerId = self._routerIdByPipeId.get(pipeId, None)
                    if routerId is None:
                        # first message from the remote peer on this pipe is its routerId
                        content = msg.bytes.decode()
                        routerId = int(content)
                        self._routerIdByPipeId[pipeId] = routerId
                        _PPMsg('resolved', f'<{_localPipeAddr(msg.pipe)}> to <{routerId}>')
                    else:
                        msg = _msgFromBytes(msg.bytes)
                        self._route(msg)
                    taskToMonitorMap[arecv(self._sMachine)] = m     # add new task to end of queue
                elif m.type == _AWAITING_CONNECTION_TIMER_EVENT:
                    raise NotYetImplemented('_AWAITING_CONNECTION_TIMER_EVENT')
                    # _queuedMsgByRouterId
                elif m.type == _TCP_EVENT:
                    raise NotYetImplemented('_TCP_EVENT')
                elif m.type == _TIMER_EVENT:
                    fnId = m.args
                    raise NotYetImplemented('_TIMER_EVENT')
                else:
                    raise ProgrammerError(f'Unknown monitor type "{m.type}".')

        for t in pending:
            t.cancel()
            await until(timeout=0)
        for t in taskToMonitorMap.keys():
            t.cancel()
            await until(timeout=0)
        _PPMsg('shutdown', '')


    # DISPLAY

    def __str__(self):
        return f'Router<{self._name}::{self._routerId}>'


class _MesagesAwaitingConnection:
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
    simpleion.dump(msg.fromAddr.routerId, bytes, binary=True)
    simpleion.dump(msg.fromAddr.connectionId, bytes, binary=True)
    # if msg.toAddr == VLM.PUB:
    #     simpleion.dump(None, bytes, binary=True)
    #     simpleion.dump(None, bytes, binary=True)
    # else:
    simpleion.dump(msg.toAddr.routerId, bytes, binary=True)
    simpleion.dump(msg.toAddr.connectionId, bytes, binary=True)
    simpleion.dump(msg.subject, bytes, binary=True)
    simpleion.dump(msg._msgId, bytes, binary=True)
    simpleion.dump(msg._replyId, bytes, binary=True)
    simpleion.dump(msg.contents, bytes, binary=True)
    simpleion.dump(msg.meta, bytes, binary=True)
    return bytes.getvalue()

def _msgFromBytes(bytes):
    values = simpleion.load(io.BytesIO(bytes), single_value=False)
    schema, fromAddrSocketAddr, fromAddrConnId, toAddrSocketAddr, toAddrConnId, subject, _msgId, _replyId, contents, meta = values
    schema = str(schema)
    fromAddrSocketAddr = str(fromAddrSocketAddr)
    fromAddrConnId = int(fromAddrConnId)
    toAddrSocketAddr = str(toAddrSocketAddr)
    toAddrConnId = int(toAddrConnId)
    subject = str(subject)
    _msgId = int(_msgId)
    _replyId = int(_replyId) if _replyId else None
    assert schema == '1'
    if toAddrSocketAddr:
        msg = Msg(Addr(None, toAddrSocketAddr, toAddrConnId), subject, contents)
    else:
        raise NotYetImplemented('PUB')
        # msg = Msg(VLM.PUB, subject, contents)
    msg.fromAddr = Addr(None, fromAddrSocketAddr, fromAddrConnId)
    msg._msgId = _msgId
    msg._replyId = _replyId
    msg.meta = meta
    # OPEN: assert stream at end
    return msg


# **********************************************************************************************************************
# Logging and pretty-printing
# **********************************************************************************************************************

def _PPMsg(prefix, msg):
    print(f'{prefix + ":":<15} {msg}')
    return msg


# **********************************************************************************************************************
# Utils
# **********************************************************************************************************************

def _ipcAddr(pid):
    return f'ipc:///tmp/router_{pid}'

def _tcpAddr(ip, port):
    if ip.upper() == 'LOCALHOST':
        return f'tcp://127.0.0.1:{port}'
    else:
        return f'tcp://{ip}:{port}'

def _localPipeAddr(pipe):
    # in ipc local_address and remote_address are the same string - so display pipe id to distinguish remote peers
    return f'<{pipe.remote_address!s}::{pipe.id}>'
