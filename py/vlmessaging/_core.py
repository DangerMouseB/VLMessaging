# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# Python imports
import itertools, logging, pynng, asyncio, weakref, collections, io, os, random, sys, uuid, traceback, datetime, inspect
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
_mEpSeed = itertools.count(os.getpid())    # OPEN: random number instead? any advantages or security concern about using pid?

_STOP_DIALING_ME_AND_CLOSE = "STOP_DIALING_ME_AND_CLOSE"

_ROUTER_REP = 0
_DIRECTORY_REP = 1
_GATEWAY_REP = 2
_FIRST_CONNECTION_ID = 3
_HUB_ROUTER_ID = 1
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
_TIMERLIST_CHANGED = 8

_eventPPNameById = {
    _MSG_ARRIVED: 'MSG_ARRIVED',
    _SOCK_RECV: 'SOCK_RECV',
    _TIMER: 'TIMER',
    _SHUTDOWN_TRIGGERED: 'SHUTDOWN_TRIGGERED',
    _TASKLIST_CHANGED: 'TASKLIST_CHANGED',
    _CONNECTION_ATTEMPT_TIMEOUT: 'CONNECTION_ATTEMPT_TIMEOUT',
}

_SET_ROUTE_BACK_TO_ME = 'SET_ROUTE_BACK_TO_ME'

_EP_MACHINE = "MACHINE"
_EP_NETWORK = "NETWORK"

_addressesInUse = set()

_DEFAULT_LOCAL_CONNECTION_TIMESOUT = 2000

class ExitMessageHandler(Exception): pass


# **********************************************************************************************************************
# Public Structs
# **********************************************************************************************************************

Addr = collections.namedtuple('Addr', (
    'nEp',      # network level endpoint - e.g. "tcp://host:port"
    'mEp',      # machine level endpoint - e.g. "ipc:///tmp/router_4353"
    'rEp'       # router level endpoint - e.g. 1, 2, 3
))
def Addr__str__(self):
    if self.nEp is not None:
        if self.mEp is not None:
            splits = self.mEp.rsplit('/', 1)
            return f'<{self.nEp}::{splits[-1]}::{self.rEp}>'
        else:
            return f'<{self.nEp}::None::{self.rEp}>'
    else:
        if self.mEp is not None:
            splits = self.mEp.rsplit('/', 1)
            return f'<{splits[-1]}::{self.rEp}>'
        else:
            return f'<{self.rEp}>'
def Addr_fromSeq(t):
    return Addr(t[0], t[1], t[2])
Addr.__str__ = Addr__str__
Addr.fromSeq = Addr_fromSeq


# OPEN: add the connection's 'uuid'?
Entry = collections.namedtuple('Entry', ('addr', 'service', 'params', 'vnets', 'perms'))
def fromSeq(t):
    return Entry(
        Addr.fromSeq(t[0]),
        t[1],
        t[2],
        t[3],
        [Perm.fromSeq(p) for p in t[4]] if t[4] else None
    )
Entry.fromSeq = fromSeq


Perm = collections.namedtuple('Perm', ('domain', 'permId'))
def Perm_fromSeq(t):
    return Perm(t[0], t[1])
Perm.fromSeq = Perm_fromSeq


class Msg:

    __slots__ = ('replyAddr', 'toAddr', 'subject', '_msgId', '_replyId', 'contents', 'meta')

    def __init__(self, toAddr, subject, contents=None):
        self.replyAddr = None
        self.toAddr = toAddr
        self.subject = subject
        self._msgId = None
        self._replyId = None
        self.contents = contents
        self.meta = {}

    def reply(self, contents, *, subject=Missing):
        answer = Msg(self.replyAddr, subject or self.subject, contents)
        answer._replyId = self._msgId
        return answer

    @property
    def isReply(self):
        return self._replyId is not None

    def clone(self):
        clone = Msg(self.toAddr, self.subject, self.contents)
        clone.replyAddr = self.replyAddr
        clone._msgId = self._msgId
        clone._replyId = self._replyId
        clone.meta = dict(self.meta)
        return clone

    def __repr__(self):
        if self._replyId is None:
            return f'Msg({self.replyAddr!s} => {self.toAddr!s}, subject: "{self.subject!s}", msgId: {self._msgId})'
        else:
            return f'Msg({self.replyAddr!s} => {self.toAddr!s}, subject: "{self.subject!s}" REPLY, msgId: {self._msgId}, replyId: {self._replyId})'

LocalRemoteEps = collections.namedtuple('LocalRemoteEps', ('local', 'remote'))


# **********************************************************************************************************************
# Connection
# **********************************************************************************************************************

class Connection:

    __slots__ = ('_router', '_msgArrivedFn', '_futureAndSubjectsByReplyId', '_msgIdSeed', 'addr', 'uuid', '__weakref__')

    def __init__(self, router, addr, fn):
        self._router = router
        self._msgArrivedFn = fn
        self._futureAndSubjectsByReplyId = {}
        self._msgIdSeed = itertools.count(1)
        self.addr = addr
        self.uuid = uuid.uuid4().hex

    async def send(self, msg, timeout=Missing, additional_subjects=Missing):
        # return reply, Missing if timeout exceeded or None if no timeout
        msg._msgId = next(self._msgIdSeed)
        if not msg.replyAddr:
            if msg.toAddr.nEp is None:
                if msg.toAddr.mEp is None:
                    msg.replyAddr = Addr(None, None, self.addr.rEp)
                else:
                    msg.replyAddr = Addr(None, self.addr.mEp, self.addr.rEp)
            else:
                msg.replyAddr = self.addr
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
        self._router._dropInboxFor(self.addr.rEp)

    @property
    def directoryAddr(self):
        return Addr(None, None, _DIRECTORY_REP)

    async def shutdown(self):
        self._router.shutdown()
        await until(self._router.hasShutdown)

    def mEpListen(self, ep, start=Missing, end=Missing):
        return self._router.mEpListen(ep, start, end)

    def nEpListen(self, ep, start=Missing, end=Missing):
        return self._router.nEpListen(ep, start, end)

    def scheduleFn(self, fn, after):
        return self._router.scheduleFn(fn, after)



# **********************************************************************************************************************
# Router
# **********************************************************************************************************************

class Router:

    __slots__ = (
        '_name',
        '_mode',
        '_connectionByREp',
        '_inboxByREp',                  # each connection's queue
        '_rEpSeed',
        '_mEps',
        '_nEps',
        '_sbRouter',                    # router (ipc) socket bundle
        '_sbHub',                       # hub directory (ipc) socket bundle - _routerSbByName
        '_sbGateway',                   # gateway (ipc) socket bundle
        '_sbNetwork',                   # network (tcp) socket bundle - _networkSbByEndpoint
        '_taskListChanged',
        '_isShuttingDown',              # an Event signalling that the router is shutting down
        '_isShuttingDownTask',          # a task that waits for the isShuttingDown event that connections can use to timeout
        '_hasShutdown',                 # an Event signalling that the router has shutdown
        '_timerListChanged',            # an Event signalling that the timer list has a new first timer
        '_timerFnsByTime',
        '_nextTime',                    # the next time a callback is scheduled for
    )

    # PUBLIC API

    def __init__(self, mode=VLM.MACHINE_MODE, name=Missing):
        if mode not in (VLM.LOCAL_MODE, VLM.MACHINE_MODE, VLM.NETWORK_MODE):
            raise ValueError(f'Unknown router mode "{mode}".')

        self._name = name
        self._mode = mode

        self._connectionByREp = weakref.WeakValueDictionary()
        self._inboxByREp = {}
        self._rEpSeed = itertools.count(_FIRST_CONNECTION_ID)

        self._mEps = []
        self._nEps = []
        self._sbRouter = Missing
        self._sbHub = Missing
        self._sbGateway = Missing
        self._sbNetwork = Missing

        self._taskListChanged = asyncio.Event()
        self._isShuttingDown = asyncio.Event()
        self._isShuttingDownTask = taskOnEvent(self._isShuttingDown)
        self._hasShutdown = asyncio.Event()
        self._timerListChanged = asyncio.Event()
        self._timerFnsByTime = {}
        self._nextTime = Missing

        if mode in (VLM.MACHINE_MODE, VLM.NETWORK_MODE):
            id1 = next(_mEpSeed)
            self.mEpListen('ipc:///tmp/router_{N}', id1, id1 + _MAX_IPC_LISTEN_ATTEMPTS)

        if mode is VLM.NETWORK_MODE:
            self._sbNetwork = _NngSocketBundle(self, _EP_NETWORK)

        if name is Missing: self._name = f'router_{self._mEps[0]}' if self._mEps else 'local'

        asyncio.create_task(self._mainLoop())
        asyncio.create_task(self._timerLoop())


    def newConnection(self, fn=Missing):
        return self._newConnection(next(self._rEpSeed), fn)

    def scheduleFn(self, fn, after):
        assert inspect.iscoroutinefunction(fn)
        if isinstance(after, datetime.timedelta):
            t = datetime.datetime.now() + after
        elif isinstance(after, (int, float)):
            t = datetime.datetime.now() + datetime.timedelta(milliseconds=after)
        self._timerFnsByTime.setdefault(t, []).append(fn)
        if self._nextTime is Missing or t < self._nextTime:
            self._nextTime = t
            self._timerListChanged.set()

    def unscheduleFn(self, fn):
        for t, fns in dict(self._timerFnsByTime).items():
            if fn in list(fns):
                fns.remove(fn)
            if not fns:
                self._timerFnsByTime.pop(t)

    def unscheduleFnAt(self, fn, at):
        if fn in (fns:=self._timerFnsByTime.get(at, [])):
            fns.remove(fn)
            if not fns:
                self._timerFnsByTime.pop(t)

    def mEpListen(self, mEp, start=Missing, end=Missing):
        return self._listen(mEp, start, end)

    def nEpListen(self, nEp, start=Missing, end=Missing):
        return self._listen(nEp, start, end)

    def shutdown(self):
        self._connectionByREp = {}
        self._isShuttingDown.set()

    @property
    def hasShutdown(self):
        return self._hasShutdown


    # CONNECTION MANAGEMENT

    def _listen(self, ep, start=Missing, end=Missing):
        # OPEN: can rework this when we're ready to implement a connection manager
        if ep.startswith('ipc:///tmp/router_'):
            assert self._mode is VLM.MACHINE_MODE or self._mode is VLM.NETWORK_MODE
            assert self._sbRouter is Missing
            self._sbRouter = _NngSocketBundle(self, _EP_MACHINE)
            return self._sbRouter.mEpListen(ep, start, end)
        elif ep.startswith('ipc:///tmp/hub_'):
            assert self._mode is VLM.MACHINE_MODE or self._mode is VLM.NETWORK_MODE
            assert self._sbHub is Missing
            assert end is Missing
            self._sbHub = _NngSocketBundle(self, _EP_MACHINE)
            return self._sbRouter.mEpListen(ep, start if start else 1, start if start else 1)
        elif ep.startswith('ipc:///tmp/gateway_'):
            assert self._mode is VLM.NETWORK_MODE
            assert self._sbGateway is Missing
            assert end is Missing
            self._sbGateway = _NngSocketBundle(self, _EP_MACHINE)
            return self._sbRouter.mEpListen(ep, start if start else 1, start if start else 1)
        elif ep.startswith('ipc:///'):
            # not a router, hub nor gateway listen
            raise NotYetImplemented('listen - ipc address must be /tmp/router_, /tmp/hub_ or /tmp/gateway_')
        elif ep.startswith('tcp://'):
            assert self._mode is VLM.NETWORK_MODE
            if start is Missing: assert end is Missing
            start = start if start else 1
            end = end if end else start + 1
            return self._sbNetwork.nEpListen(ep, start, end)

    def _newConnection(self, rEp, fn):
        c = Connection(self, Addr(None, self._mEps[0] if self._mEps else None, rEp), fn)
        assert rEp not in self._connectionByREp
        self._connectionByREp[rEp] = c
        self._inboxByREp[rEp] = Queue()
        self._taskListChanged.set()
        return c

    def _dropInboxFor(self, rEp):
        self._inboxByREp.pop(rEp, None)
        self._taskListChanged.set()

    def _cancelConnectingToLocal(self, mEp):
        if (msgAccumulator := self._accumulatedMsgsByRouterId.get(mEp, Missing)) is Missing: return
        self._accumulatedMsgsByRouterId.pop(mEp, None)
        self._taskListChanged.set()
        for msg in msgAccumulator.msgs():
            if msg.subject == VLM.MSG_NOT_DELIVERED:
                # don't get into a loop of undeliverable messages
                pass
            else:
                reply = msg.reply(msg.toAddr, subject=VLM.MSG_NOT_DELIVERED)
                reply._msgId = -1
                _PPMsg(f'unroutable', msg._msgId)
                self._route(reply)


    # ROUTING

    def _route(self, msg):
        nEp, mEp, rEp = msg.toAddr
        if nEp is None or nEp in self._nEps:
            if mEp is None or mEp in self._mEps:
                inbox = self._inboxByREp.get(rEp, Missing)
                if inbox:
                    _PPMsg(f'route', f'connId: {rEp}, msgId: {msg._msgId}')
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
                if self._mode is VLM.LOCAL_MODE: raise ValueError(f'{self._mode} router ("{self._name}") cannot route to another router.')
                self._sbRouter._mRoute(msg, mEp)
        else:
            if self._mode is not VLM.NETWORK_MODE: raise ValueError(f'{self._mode} router ("{self._name}") cannot route to another machine.')
            self._sbNetwork._nRoute(msg, nEp)


    # EVENT LOOPS

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
                details = taskList.pop(task)                                                # take task from the list
                _PPMsg(f'main', f'{self._name} - {_eventPPNameById[details.type]}')

                try:

                    if details.type == _MSG_ARRIVED:
                        rEp = details.args
                        msg = task.result()
                        if (conn := self._connectionByREp.get(rEp, Missing)) is not Missing:
                            inbox = self._inboxByREp[rEp]
                            # we need to schedule a new task here rather than await otherwise we block processing other events
                            asyncio.create_task(conn._deliver(msg))
                            taskList[asyncio.create_task(inbox.get())] = details           # add task to bottom of list

                    elif details.type == _SOCK_RECV:
                        incoming = task.result()
                        sb = details.args
                        pipe = incoming.pipe
                        msg = _msgFromBytes(incoming.bytes)
                        if msg.subject == _SET_ROUTE_BACK_TO_ME:
                            if pipe.id not in sb._localRemoteEpsByPipeId:
                                _PPMsg('main::SOCK_RECV', f'{self._name} received first message on channel {pipe.url}')
                                otherEp = msg.contents
                                if (pipeByPipeId := sb._pipeByPipeIdByEp.get(otherEp, Missing)) is Missing:
                                    _PPMsg('main::SOCK_RECV', f'{self._name} received otherEp {otherEp} for channel {pipe.url}')
                                    pipeByPipeId = sb._pipeByPipeIdByEp[otherEp] = {}
                                else:
                                    _PPMsg('main::SOCK_RECV', f'{self._name} - WARNING: already connected to {otherEp} - adding additional connection')
                                    sb._epsWithExcessPipes.add(otherEp)
                                # overwrite any previous mapping for this pipe.id
                                sb._localRemoteEpsByPipeId[pipe.id] = LocalRemoteEps(
                                    msg.toAddr.nEp if sb._epType == _EP_NETWORK else msg.toAddr.mEp, 
                                    otherEp
                                )
                                sb._pipeByPipeIdByEp[otherEp]  = {pipe.id:pipe} | pipeByPipeId  # make this explicit one the first in the dict

                        else:
                            _PPMsg('main::SOCK_RECV', f'{self._name} - routing {msg}')
                            if sb._epType == _EP_NETWORK:
                                if msg.replyAddr.nEp is None:
                                    # assign the repyAddr.nEp to the random port one
                                    msg.replyAddr = Addr(
                                        sb._localRemoteEpsByPipeId[pipe.id].local,
                                        msg.replyAddr.mEp,
                                        msg.replyAddr.rEp
                                    )
                                if msg.toAddr.nEp not in self._nEps:
                                    _PPMsg('main::SOCK_RECV', f'{self._name} - ERROR')
                            self._route(msg)
                        taskList[corecv(sb.sock)] = details                                 # add task to bottom of list

                    elif details.type == _CONNECTION_ATTEMPT_TIMEOUT:
                        # OPEN: cancel the dialer if it is still trying to connect, return unroutable messages to sender
                        raise NotYetImplemented('_CONNECTION_ATTEMPT_TIMEOUT')

                    elif details.type == _TASKLIST_CHANGED:
                        # remove old tasks that are no longer needed
                        tasksToRemove = []
                        for t, m in taskList.items():
                            if m.type == _MSG_ARRIVED and m.args not in self._connectionByREp:
                                tasksToRemove.append(t)   # drop closed connections
                        for t in tasksToRemove:
                            # _PPMsg(f'dropping', f'{tasksToRemove[t]}')
                            t.cancel('no longer needed')
                            await until(timeout=0)
                            # t.uncancel()    # "in cases when suppressing asyncio.CancelledError is truly desired, it is necessary to also call uncancel()"
                            taskList.pop(t)
                        await asyncio.gather(*tasksToRemove, return_exceptions=True)

                        # add any inbox tasks that are needed
                        for rEp, conn in self._connectionByREp.items():
                            if _Details(_MSG_ARRIVED, rEp) not in taskList.values():
                                taskList[coPopFront(self._inboxByREp[rEp])] = _Details(_MSG_ARRIVED, rEp)
                                _PPMsg(f'main', f'{self._name} - added MSG_ARRIVED task for connId: {rEp}')

                        # add any socket tasks that are needed
                        if self._sbRouter and _Details(_SOCK_RECV, self._sbRouter) not in taskList.values():
                            taskList[corecv(self._sbRouter.sock)] = _Details(_SOCK_RECV, self._sbRouter)
                            _PPMsg(f'main', f'{self._name} - added machine SOCK_RECV task')

                        if self._sbHub and _Details(_SOCK_RECV, self._sbHub) not in taskList.values():
                            taskList[corecv(self._sbHub.sock)] = _Details(_SOCK_RECV, self._sbHub)
                            _PPMsg(f'main', f'{self._name} - added hub SOCK_RECV task')

                        if self._sbNetwork and _Details(_SOCK_RECV, self._sbNetwork) not in taskList.values():
                            taskList[corecv(self._sbNetwork.sock)] = _Details(_SOCK_RECV, self._sbNetwork)
                            _PPMsg(f'main', f'{self._name} - added network SOCK_RECV task')

                        self._taskListChanged.clear()
                        taskList[taskOnEvent(self._taskListChanged)] = details              # add task to bottom of list

                    elif details.type == _SHUTDOWN_TRIGGERED:
                        running = False
                        break

                    else:
                        raise ProgrammerError(f'Unknown monitor type "{details.type}".')

                except BaseException as ex:
                    print(traceback.format_exc())
                    _PPMsg('!!!!', f'Error processing {_eventPPNameById[details.type]} in router {self._name}: {ex}')
                    raise

        for t in pending:
            t.cancel()
            await until(timeout=0)
        for t in taskList.keys():
            t.cancel()
            await until(timeout=0)
        if self._sbRouter: self._sbRouter.close()
        if self._sbHub: self._sbHub.close()
        if self._sbGateway: self._sbGateway.close()
        if self._sbNetwork: self._sbNetwork.close()
        self._hasShutdown.set()
        _PPMsg('shutdown', self._name)


    async def _timerLoop(self):
        taskList = {
            self._isShuttingDownTask: _Details(_SHUTDOWN_TRIGGERED, None),
            taskOnEvent(self._timerListChanged): _Details(_TIMERLIST_CHANGED, None),
        }
        running = True
        pending = []
        while running:
            self._nextTime = Missing
            for t, fns in self._timerFnsByTime.items():
                if self._nextTime is Missing or t < self._nextTime:
                    self._nextTime = t

            if self._nextTime:
                if (now := datetime.datetime.now()) < self._nextTime:
                    ms = (self._nextTime - now).total_seconds() * 1000
                    done, pending = await until(taskList.keys(), return_when=asyncio.FIRST_COMPLETED, timeout=ms)
                else:
                    # timer already expired, but check for shutdown etc before executing fn
                    done, pending = await until(taskList.keys(), return_when=asyncio.FIRST_COMPLETED, timeout=0)
            else:
                # no timers, wait indefinitely until a fn is scheduled
                done, pending = await until(taskList.keys(), return_when=asyncio.FIRST_COMPLETED, timeout=None)

            for task in done:
                details = taskList.pop(task)                                    # remove task from the list
                if details.type == _TIMERLIST_CHANGED:
                    self._timerListChanged.clear()
                    taskList[taskOnEvent(self._timerListChanged)] = details     # add task to bottom of list
                elif details.type == _SHUTDOWN_TRIGGERED:
                    running = False
                    break
                else:
                    raise ProgrammerError(f'Unknown monitor type "{details.type}".')

            if running and self._nextTime and datetime.datetime.now() >= self._nextTime:
                fns = self._timerFnsByTime.pop(self._nextTime, [])
                for fn in fns:
                    try:
                        await fn()
                    except Exception as ex:
                        _PPMsg('!!!!', f'Error executing scheduled timer function in router {self._name}: {ex}')

        for t in pending:
            t.cancel()
            await until(timeout=0)
        for t in taskList.keys():
            t.cancel()
            await until(timeout=0)
        _PPMsg('timerloop shutdown', self._name)


    # DISPLAY

    def __str__(self):
        return f'Router<{self._name}::{self._mEps[0] if self._mEps else "local"}>'



class _NngSocketBundle:
    __slots__ = (
        '_router',
        '_epType',
        '_ep',
        'sock',
        '_pipeByPipeIdByEp',        # pipe by pipeId by ep - so we know which pipe to send a msg down
        '_localRemoteEpsByPipeId',              # so we know which remote thing a msg has directly come from
        '_epsWithExcessPipes',
        '_dialerByEp',              # so we can cancel dialing if we need to
        '_msgAccumulatorByEp',      # to be checked periodically for connection, reply with unroutable on time out
    )


    # LIFECYCLE

    def __init__(self, router, epType):
        self._router = router
        self._epType = epType
        self._ep = Missing
        self.sock = pynng.Pair1(polyamorous=True)
        self.sock.add_post_pipe_connect_cb(self._onConnect)
        self.sock.add_post_pipe_remove_cb(self._onDisconnect)
        self._pipeByPipeIdByEp = {}
        self._localRemoteEpsByPipeId = {}
        self._epsWithExcessPipes = set()
        self._dialerByEp = {}
        self._msgAccumulatorByEp = {}

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = Missing


    # CONNECTION MANAGEMENT

    def nEpListen(self, template, id1, id2):
        ep = self._listen(template, id1, id2)
        if ep not in self._router._nEps:
            self._router._nEps.append(ep)
        return ep

    def mEpListen(self, template, id1, id2):
        ep = self._listen(template, id1, id2)
        if ep not in self._router._mEps:
            self._router._mEps.append(ep)
        return ep

    def _listen(self, template, id1, id2):
        assert id1 <= id2
        while id1 <= id2:
            sockAddr = template.format(N=id1)
            if sockAddr not in _addressesInUse:
                listener = Missing
                try:
                    listener = self.sock.listen(sockAddr)
                    self._ep = sockAddr
                    _PPMsg('listening', f'{self._router._name or str(self._ep)} - {self._ep}')
                    break
                except pynng.exceptions.AddressInUse as ex:
                    # OPEN: figure out how to recover from AddressInUse properly rather than just trying a new id - in the
                    #       same process in ipc mode it breaks the ability of a prior listening socket to be connected to
                    #       (I suppose the listener pointer is changed or something?)
                    _addressesInUse.add(sockAddr)
                id1 += 1
        if id1 > id2:
            raise RuntimeError(f'Unable to find a free address.')
        _addressesInUse.add(sockAddr)
        self._router._taskListChanged.set()
        return self._ep

    def _dial(self, ep, timeout):
        if ep in self._msgAccumulatorByEp: raise ValueError(f'Already dialing {ep}.')
        msgAccumulator = self._msgAccumulatorByEp[ep] = _MsgAccumulator(monotonicTimeMs() + timeout)
        self._dialerByEp[ep] = dial(self.sock, ep, block=False)
        _PPMsg('dialing_router', f'{self._router._name} dialing {ep}')
        return msgAccumulator


    # SOCKET CALLBACKS

    def _onConnect(self, pipe):
        try:
            if pipe.url.startswith('tcp://'):
                if f'tcp://{pipe.local_address}' == self._ep:
                    direction = 'incoming'
                    self._onIncomingTcpConnect(pipe)
                else:
                    direction = 'outgoing'
                    self._onOutGoingTcpConnect(pipe)
            else:
                try:
                    pipe.listener
                    direction = 'incoming'
                    self._onIncomingIpcConnect(pipe)
                except TypeError:
                    direction = 'unknown'
                    pipe.dialer                             # shouldn't raise but let's catch it anyway
                    direction = 'outgoing'
                    self._onOutGoingIpcConnect(pipe)
        except Exception as ex:
            _PPMsg('onConnect', f'#err {self._router._name} - {direction} via {pipe.url} - {repr(ex)}')

    def _onIncomingIpcConnect(self, pipe):
        # in nng ipc we don't know who the remote is until they send a message about themselves, they know who we are
        _PPMsg('onConnectIpcIn', f'{self._router._name} - incoming on {pipe.url}')

    def _onOutGoingIpcConnect(self, pipe):
        # we know who we are connecting to since we dialed them so send our id right away
        ep = pipe.url
        _PPMsg('onConnectIpcOut', f'{self._router._name} - connected to {ep}')
        if (pipeByPipeId := self._pipeByPipeIdByEp.get(ep, Missing)) is Missing:
            pipeByPipeId = self._pipeByPipeIdByEp[ep] = {}
        if pipe.id not in pipeByPipeId: pipeByPipeId[pipe.id] = pipe
        msg = Msg(Addr(None, None, _ROUTER_REP), subject=_SET_ROUTE_BACK_TO_ME, contents=self._ep)
        msg.replyAddr = Addr(None, None, None)
        send(pipe, _msgAsBytes(msg), block=False)
        if (msgAccumulator := self._msgAccumulatorByEp.pop(ep, Missing)) is not Missing:
            for msg in msgAccumulator.msgs:
                _PPMsg('onConnectIpcOut', f'{self._router._name} - sending accumulated {msg}')
                send(pipe, _msgAsBytes(msg), block=False)

    def _onIncomingTcpConnect(self, pipe):
        # for a tcp connection we only know the dialer's randomly assigned outgoing address, so we can only setup
        # routing to that address unless they send a message identifying themselves properly
        nEp = f'tcp://{pipe.remote_address}'
        if (pipeByPipeId := self._pipeByPipeIdByEp.get(nEp, Missing)) is Missing:
            pipeByPipeId = self._pipeByPipeIdByEp[nEp] = {}
        if pipe.id not in pipeByPipeId:
            pipeByPipeId[pipe.id] = pipe
        self._localRemoteEpsByPipeId[pipe.id] = LocalRemoteEps(f'tcp://{pipe.local_address}', nEp)
        _PPMsg('onConnectTcpIn', f'{self._router._name} - incoming from randomly assigned {nEp}')

    def _onOutGoingTcpConnect(self, pipe):
        localNEpRandomPort = f'tcp://{pipe.local_address}'
        nEp = f'tcp://{pipe.remote_address}'
        _PPMsg('onConnectTcpOut', f'{self._router._name} - connected from {localNEpRandomPort} to {nEp}')
        if (pipeByPipeId := self._pipeByPipeIdByEp.get(nEp, Missing)) is Missing:
            pipeByPipeId = self._pipeByPipeIdByEp[nEp] = {}
        if pipe.id not in pipeByPipeId:
            pipeByPipeId[pipe.id] = pipe
        self._localRemoteEpsByPipeId[pipe.id] = LocalRemoteEps(localNEpRandomPort, nEp)
        if localNEpRandomPort not in self._router._nEps:
            self._router._nEps.append(localNEpRandomPort)
        # tell the other end who we are if we are listening on a known network nEp else don't tell them anything
        if self._ep:
            msg = Msg(Addr(nEp, None, _ROUTER_REP), _SET_ROUTE_BACK_TO_ME, self._ep)
            msg.replyAddr = Addr(self._ep or localNEpRandomPort, None, _ROUTER_REP)
            send(pipe, _msgAsBytes(msg), block=False)
        if (msgAccumulator := self._msgAccumulatorByEp.pop(nEp, Missing)) is not Missing:
            for msg in msgAccumulator.msgs:
                if msg.replyAddr.nEp is None:
                    msg = msg.clone()
                    msg.replyAddr = Addr(
                        self._ep or localNEpRandomPort,
                        msg.replyAddr.mEp,
                        msg.replyAddr.rEp
                    )
                _PPMsg('onConnectIpcOut', f'{self._router._name} - sending accumulated {msg}')
                send(pipe, _msgAsBytes(msg), block=False)

    def _onDisconnect(self, pipe):
        try:
            ep = self._localRemoteEpsByPipeId.pop(pipe.id, Missing)
            if ep:
                if (pipeByPipeId := self._pipeByPipeIdByEp.get(ep, Missing)) is not Missing:
                    pipeByPipeId.pop(pipe.id, None)
                # OPEN: drop the random port nEp
                _PPMsg('onDisconnect', f'{self._router._name} <{ep}> - {pipeConnectionType(pipe)} on channel <{pipe.url}>')
            else:
                _PPMsg('onDisconnect', f'{self._router._name} - {pipeConnectionType(pipe)} on channel {pipe.url}')
        except Exception as ex:
            _PPMsg('onDisconnect', f'#err {self._router._name} - error processing disconnect on channel {pipe.url}: {repr(ex)}')


    # ROUTING

    def _mRoute(self, msg, mEp):
        if (pipeByPipeId := self._pipeByPipeIdByEp.get(mEp, Missing)) is Missing:
            if (msgAccumulator := self._msgAccumulatorByEp.get(mEp, Missing)) is Missing:
                msgAccumulator = self._dial(mEp, _DEFAULT_LOCAL_CONNECTION_TIMESOUT)
            msgAccumulator.queueMsg(msg)
        else:
            if msg.replyAddr.mEp is None:
                raise NotYetImplemented('msg.replyAddr.mEp is None')
            pipe = firstValue(pipeByPipeId)
            cosend(pipe, _msgAsBytes(msg))  # we might be able to async send this instead but not sure we gain much

    def _nRoute(self, msg, nEp):
        if (pipeByPipeId := self._pipeByPipeIdByEp.get(nEp, Missing)) is Missing:
            accumulate = True
        else:
            pipe = firstValue(pipeByPipeId)
            if msg.replyAddr.nEp is None:
                if (eps := self._localRemoteEpsByPipeId.get(pipe.id, Missing)) is Missing:
                    accumulate = True
                else:
                    # assign the repyAddr.nEp to the random port one
                    msg = msg.clone()
                    msg.replyAddr = Addr(
                        self._ep or eps.local,
                        msg.replyAddr.mEp,
                        msg.replyAddr.rEp
                    )
                    accumulate = False
            else:
                accumulate = False
        if accumulate:
            if (msgAccumulator := self._msgAccumulatorByEp.get(nEp, Missing)) is Missing:
                msgAccumulator = self._dial(nEp, _DEFAULT_LOCAL_CONNECTION_TIMESOUT)
            msgAccumulator.queueMsg(msg)
        else:
            if (msgAccumulator := self._msgAccumulatorByEp.pop(nEp, Missing)) is not Missing:
                for accMsg in msgAccumulator.msgs:
                    _PPMsg('_nRoute', f'{self._router._name} - sending accumulated {accMsg}')
                    if msg.replyAddr.nEp is None:
                        # assign the repyAddr.nEp to the random port one
                        accMsg = msg.clone()
                        accMsg.replyAddr = Addr(
                            self._ep or nEp,
                            accMsg.replyAddr.mEp,
                            accMsg.replyAddr.rEp
                        )
                    cosend(pipe, _msgAsBytes(accMsg))
            cosend(pipe, _msgAsBytes(msg))      # we might be able to async send this instead but not sure we gain much


    # DISPLAY

    def __repr__(self):
        return f'SocketBundle<{self._router._name}::{self._ep}>'



# **********************************************************************************************************************
# Directory
# **********************************************************************************************************************

class Directory:
    _conn: Connection
    # OPEN: add security so agents can only add / remove their own entries and see only what they are allowed to see,
    #       but what about telling a directory that a connection didn't get delivered
    
    _SHARE_ENTRIES = 'SHARE_ENTRIES'
    _BAD_ENTRIES = 'BAD_ENTRIES'
    _GET_VNETS = 'GET_VNETS'
    
    __slots__ = (
        '_routerName',
        '_conn',
        '_entries',                 # [Entry]
        '_potentiallyStale',        # set() of addr we haven't heard from in a while
        '_heartbeatEntriesTimeout',
        '_vnets',                   # list of vnet names
        '_hubListen',               # mEp or Missing
        '_hubListener',             # listener object or Missing
        '_hubs',                    # list of mEp
        '_gatewayListen',           # mEp or Missing
        '_gatewayListener',         # listener object or Missing
        '_gateways',                # list of mEp
        '_netListen',               # nEp or Missing
        '_netListener',             # listener object or Missing
        '_netHubs',                 # list of nEp
        '_beaconAnnounce',          # UDP multicast address or Missing
        '_beaconListen',            # UDP multicast address or Missing
        '_ensureNetworkWait',       # time to wait before trying to ensure network again
        '_vnetsByHub',               # vnet name by hub mEp or hub nEp
    )

    def __init__(self,
            router,
            vnets=Missing,              # list
            hubListen=Missing,          # mEp or Missing
            hubs=Missing,               # list of mEp
            gatewayListen=Missing,      # mEp
            gateways=Missing,           # list of mEp
            netListen=Missing,          # nEp or Missing
            netHubs=Missing,            # list of nEp
            beaconAnnounce=Missing,     # beacon address to announce myself on
            beaconListen=Missing,       # address to listen for beacons on
            heartbeatEntriesTimeout=Missing,
    ):

        if router._connectionByREp.get(_DIRECTORY_REP, Missing) is not Missing:
            raise RuntimeError('A Directory already exists on this router')
        self._routerName = router._name
        self._conn = router._newConnection(_DIRECTORY_REP, self.msgArrived)
        self._heartbeatEntriesTimeout = \
            _DEFAULT_HEARTBEAT_ENTRIES_INTERVAL \
            if heartbeatEntriesTimeout is Missing \
            else (Missing if heartbeatEntriesTimeout <= 0 else heartbeatEntriesTimeout)
        self._entries = []
        self._potentiallyStale = set()
        self._vnets = [] if vnets is Missing else vnets
        self._hubListen = hubListen
        self._hubListener = Missing
        self._hubs = [] if hubs is Missing else hubs
        self._vnetsByHub = {}
        self._gatewayListen = gatewayListen
        self._gatewayListener = Missing
        self._gateways = [] if gateways is Missing else gateways
        self._netListen = netListen
        self._netListener = Missing
        self._netHubs = [] if netHubs is Missing else netHubs
        self._ensureNetworkWait = 50
        self._conn.scheduleFn(self._ensureNetwork, after=self._ensureNetworkWait)
        if self._heartbeatEntriesTimeout:
            self._conn.scheduleFn(self._heartbeatEntries, after=self._heartbeatEntriesTimeout)


    async def _ensureNetwork(self):
        try:
            await self._ensureNetworkImpl()
        except Exception as ex:
            _PPMsg('d:ensureNetwork', f'{self._routerName}: Error ensuring network: {repr(ex)}')
            await self._ensureNetworkImpl()
            raise
        finally:
            # schedule next ensure network attempt
            self._ensureNetworkWait = max(min(self._ensureNetworkWait * 2, 10000), 50)
            self._conn.scheduleFn(self._ensureNetwork, after=self._ensureNetworkWait)

    async def _ensureNetworkImpl(self):

        # try to listen as a machine hub (if specified)
        if self._hubListen and not self._hubListener:
            try:
                self._hubListener = self._conn.mEpListen(self._hubListen)
            except Exception as ex:
                _PPMsg('d:ensureNetwork', f'{self._routerName}: Another router is already listening on {self._hubListen} - {repr(ex)}')
                
        # share entries with machine hubs
        for hub in self._hubs:
            if hub != self._hubListen:
                entriesToShare = [e for e in self._entries if VLM.LOCAL_VNET in e.vnets]
                await self._conn.send(Msg(Addr(None, hub, _DIRECTORY_REP), Directory._SHARE_ENTRIES, entriesToShare))

        # try to listen as a gateway (if specified)
        if self._gatewayListen and not self._gatewayListener:
            try:
                self._gatewayListener = self._conn.mEpListen(self._gatewayListen)
            except Exception as ex:
                _PPMsg('d:ensureNetwork', f'{self._routerName}: Another router is already listening on {self._gatewayListen} - {repr(ex)}')

        # network hubs
        if self._netListen and not self._netListener:
            try:
                self._netListener = self._conn.nEpListen(self._netListen)
            except Exception as ex:
                _PPMsg('d:ensureNetwork', f'{self._routerName}: Another router is already listening on {self._netListen} - {repr(ex)}')

        # share entries with network hubs
        for hub in self._netHubs:
            if hub != self._netListen:
                if vnets := self._vnetsByHub.get(hub, Missing) is Missing:
                    await self._conn.send( Msg(Addr(hub, None, _DIRECTORY_REP), Directory._GET_VNETS) )
                else:
                    # share my entries with net hub
                    entriesToShare = [e for e in self._entries if _anyIn(e.vnets, vnets)]
                    await self._conn.send(Msg(Addr(hub, None, _DIRECTORY_REP), Directory._SHARE_ENTRIES, entriesToShare))


    async def msgArrived(self, msg):
        self._potentiallyStale.discard(msg.replyAddr)
        _PPMsg(f'd:{msg.subject}', f'{self._routerName} {msg}')

        if msg.subject == VLM.REGISTER_ENTRY:
            addr, service, params, vnets, perms = msg.contents
            for a, s, p, _, _ in self._entries:
                if a == addr and s == service and p == params:
                    await self._conn.send( msg.reply(True) )
                    return
            self._entries.append( msg.contents )
            self._conn._router.unscheduleFn(self._ensureNetwork)
            self._conn._router.scheduleFn(self._ensureNetwork, after=200)
            await self._conn.send(msg.reply(True))

        elif msg.subject == VLM.UNREGISTER_ENTRY:
            entry = msg.contents
            self._entries = [e for e in self._entries if e != entry]
            self._conn._router.unscheduleFn(self._ensureNetwork)
            self._conn._router.scheduleFn(self._ensureNetwork, after=200)
            await self._conn.send(msg.reply(True))

        elif msg.subject == VLM.UNREGISTER_ADDR:
            addr = msg.contents
            self._entries = [e for e in self._entries if e.addr != addr]
            self._conn._router.unscheduleFn(self._ensureNetwork)
            self._conn._router.scheduleFn(self._ensureNetwork, after=200)
            await self._conn.send(msg.reply(True))

        elif msg.subject == VLM.GET_ENTRIES:
            if msg.contents:
                await self._conn.send(msg.reply([e for e in self._entries if e.service == msg.contents]))
            else:
                await self._conn.send(msg.reply(self._entries))

        elif msg.subject == Directory._GET_VNETS:
            if not msg.isReply:
                # OPEN: only reply if I am acting as a hub
                await self._conn.send(msg.reply(self._vnets))
            else:
                self._vnetsByHub[msg.replyAddr.nEp] = msg.contents

        elif msg.subject == Directory._BAD_ENTRIES:
            _PPMsg(f'd:{msg.subject}', f'{self._routerName} - I was told I send bad entries!!')
        
        elif msg.subject == Directory._SHARE_ENTRIES:
            _PPMsg(f'd:{msg.subject}', f'{self._routerName} received {len(msg.contents)} entries to share')
            entries = []
            for seq in msg.contents:
                try:
                    _PPMsg(f'd:{msg.subject}', f'{self._routerName} processing shared entry: {seq}')
                    entries.append(Entry.fromSeq(seq))
                except Exception as ex:
                    _PPMsg(f'd:{msg.subject}', f'{self._routerName} - invalid entry received: {repr(ex)}')
                    reply = Msg(msg.replyAddr, Directory._BAD_ENTRIES, None)
                    await self._conn.send(reply)
                    return
            for entry in entries:
                for e in self._entries:
                    if e.addr == entry.addr and e.service == entry.service and e.params == entry.params:
                        break
                else:
                    self._entries.append(entry)
            if not msg.isReply:
                if msg.replyAddr.nEp:
                    # just share my entries that are in the vnets the hub is interested in
                    remotesVnets = self._vnetsByHub.get(msg.replyAddr.nEp, [])
                    vnetEntries = [e for e in self._entries if _anyIn(e.vnets, self._vnets)]
                    entries = []
                    for e in vnetEntries:
                        if e.addr.nEp is None:
                            entries.append(Entry(
                                Addr(msg.toAddr.nEp, e.addr.mEp, e.addr.rEp),
                                e.service,
                                e.params,
                                e.vnets,
                                e.perms
                            ))
                else:
                    # share all except my local entries
                    entries = [e for e in self._entries if e.vnets is not None]
                await self._conn.send(msg.reply(entries))

        else:
            return [VLM.HANDLE_PING, VLM.HANDLE_DOES_NOT_UNDERSTAND]


    async def _heartbeatEntries(self):
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
    simpleion.dump(msg.replyAddr.nEp, bytes, binary=True)       # string or None
    simpleion.dump(msg.replyAddr.mEp, bytes, binary=True)       # string or None
    simpleion.dump(msg.replyAddr.rEp, bytes, binary=True)       # int or None
    simpleion.dump(msg.toAddr.nEp, bytes, binary=True)          # string or None
    simpleion.dump(msg.toAddr.mEp, bytes, binary=True)          # string
    simpleion.dump(msg.toAddr.rEp, bytes, binary=True)          # int
    simpleion.dump(msg.subject, bytes, binary=True)             # string
    simpleion.dump(msg._msgId, bytes, binary=True)              # int
    simpleion.dump(msg._replyId, bytes, binary=True)            # int or None
    simpleion.dump(msg.contents, bytes, binary=True)            # any ION serializable
    simpleion.dump(msg.meta, bytes, binary=True)                # dict
    return bytes.getvalue()

def _msgFromBytes(bytes):
    try:
        values = simpleion.load(io.BytesIO(bytes), single_value=False)
        schema, replyEndpoint, replyRouterId, replyConnId, toEndpoint, toRouterId, toConnId, subject, _msgId, _replyId, contents, meta = values
        assert _toPy(schema) == '1'
        msg = Msg(Addr(_toPy(toEndpoint), _toPy(toRouterId), _toPy(toConnId)), _toPy(subject), _toPy(contents))
        msg.replyAddr = Addr(_toPy(replyEndpoint), _toPy(replyRouterId), _toPy(replyConnId))
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

class _MsgAccumulator:
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

def _anyIn(As, Bs):
    for a in As:
        if a in Bs:
            return True
    return False
