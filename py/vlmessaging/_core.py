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
from vlmessaging.utils import until
from vlmessaging import _constants as VLM


_logger = logging.getLogger(__name__)
random.seed(int.from_bytes(os.urandom(8), 'big'))


_DIRECTORY_CONNECTION_ID = 1
_FIRST_CONNECTION_ID = _DIRECTORY_CONNECTION_ID + 1
_MACHINE_HUB_ROUTER_ID = 0
_MAX_IPC_LISTEN_ATTEMPTS = 1000
_DEFAULT_HEARTBEAT_ENTRIES_TIMEOUT = 10_000


Monitor = collections.namedtuple('Monitor', ('type', 'args'))
_INBOX_EVENT = 1
_IPC_EVENT = 2
_TCP_EVENT = 3
_TIMER_EVENT = 4
_SHUTDOWN_EVENT = 5

class ExitMessageHandler(Exception): pass


# **********************************************************************************************************************
# Structs
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
                        elif instruction == VLM.HANDLE_DOES_NOT_UNDERSTAND:
                            if msg.subject == VLM.DOES_NOT_UNDERSTAND:
                                handled = True
                            else:
                                _PPMsg(f'UNHANDLED SUBJECT', msg)
                                await self.send(msg.reply(msg.subject, subject=VLM.DOES_NOT_UNDERSTAND))
                                handled = True
                        else:
                            raise SyntaxError(f'Unknown instruction "{msg.subject}".')
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
                    timeout=timeout / 1000,
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

    __slots__ = (
        '_sIpc',                    # socket for connections with other routers on this machine
        '_ipcPipeByRouterId',
        '_sIpcHub',                 # socket for finding the router that has the machine level hub directory
        '_searchForIpcHub',
        '_sRemotePeerListener',     # remote peer connections
        '_remotePipeByAddr',
        '_sRemoteByAddr',
        '_routerId',
        '_connectionIdSeed',
        '_connectionById',
        '_inboxById',
        '_refreshTasksToMonitor',
        '_isShuttingDown',          # an Event signalling that the router is shutting down
        '_hasShutdown',             # an Event signalling that the router has shutdown
        '_isShuttingDownTask',      # a task that waits for the isShuttingDown event that connections can use to timeout
        '_directory',
        '_canHostIpcHubDirectory',
        '_scheduledCallbacksByFnId',
        '_pipeByPipeId',            # when we get a new pipe we store it here
        '_pipeIdByRouterId',
        '_routerIdByPipeId'
    )


    def __init__(self, mode=VLM.MACHINE_MODE, canHostIpcHubDirectory=True):
        if mode not in (VLM.LOCAL_MODE, VLM.MACHINE_MODE, VLM.NETWORK_MODE):
            raise ValueError(f'Unknown router mode "{mode}".')

        self._sIpc, self._ipcPipeByRouterId, self._sIpcHub = Missing, {}, Missing
        self._searchForIpcHub = False
        self._sRemotePeerListener, self._remotePipeByAddr, self._sRemoteByAddr = Missing, {}, Missing
        self._connectionById , self._inboxById = weakref.WeakValueDictionary(), {}
        self._connectionIdSeed, self._refreshTasksToMonitor = itertools.count(_FIRST_CONNECTION_ID), False
        self._isShuttingDown = asyncio.Event()
        self._hasShutdown = asyncio.Event()
        self._isShuttingDownTask = asyncio.create_task(self._isShuttingDown.wait())
        self._routerId = os.getpid()
        self._canHostIpcHubDirectory = canHostIpcHubDirectory
        self._scheduledCallbacksByFnId = {}

        self._directory = Directory(self)
        if mode in (VLM.MACHINE_MODE, VLM.NETWORK_MODE):
            # create _sIpc socket
            self._sIpc = pynng.Pair1(polyamorous=True)
            self._sIpc.add_pre_pipe_connect_cb(self._sIpcPreConnectCb)
            self._sIpc.add_post_pipe_connect_cb(self._sIpcPostConnectCb)
            self._sIpc.add_post_pipe_remove_cb(self._sIpcPostRemoveCb)
            i = 0
            while i < _MAX_IPC_LISTEN_ATTEMPTS:
                try:
                    self._sIpc.listen(_ipcAddr(self._routerId + i))
                    break
                except pynng.exceptions.AddressInUse as ex:
                    i += 1
            if i >= _MAX_IPC_LISTEN_ATTEMPTS:
                raise RuntimeError(f'Unable to find a free Ipc address from {self._routerId} to {self._routerId+_MAX_IPC_LISTEN_ATTEMPTS} on this machine.')
            else:
                self._routerId += i

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

        asyncio.create_task(self._processEventsUntilShutdown())


    def scheduleCallback(self, fn, every=Missing):
        # OPEN: move this to the routers main loop so can be cancelled cleanly on shutdown and make debugging easier
        fnId = id(fn)
        if fnId in self._scheduledCallbacksByFnId:
            raise ProgrammerError(f'Callback function {fn} is already scheduled.')
        async def callbackLoop():
            try:
                while not self._isShuttingDown.is_set():
                    await asyncio.sleep(every / 1000)
                    fn()
            except asyncio.CancelledError:
                pass
        task = asyncio.create_task(callbackLoop())
        self._scheduledCallbacksByFnId[fnId] = task

    def unscheduleCallback(self, fn):
        if fnId := id(fn) in self._scheduledCallbacksByFnId:
            self._scheduledCallbacksByFnId.pop(fnId).cancel()

    def _checkMachineHubConnection(self):
        if not (hubPipe := self._ipcPipeByRouterId.get(_MACHINE_HUB_ROUTER_ID, Missing)):
            if not self._sIpcHub and self._canHostIpcHubDirectory:
                # try to become the machine hub directory
                try:
                    s = pynng.Pair1(polyamorous=True)
                    s.listen(_ipcAddr(_MACHINE_HUB_ROUTER_ID))
                    s.add_pre_pipe_connect_cb(self._sIpcHubPreConnectCb)
                    s.add_post_pipe_remove_cb(self._sIpcHubPostRemoveCb)
                    self._sIpcHub = s
                except pynng.exceptions.AddressInUse as ex:
                    pass
            if not self._sIpcHub:
                # we do not host the machine hub directory try to connect to it
                try:
                    self._ipcPipeByRouterId[_MACHINE_HUB_ROUTER_ID] = self._sIpc.dial(_ipcAddr(_MACHINE_HUB_ROUTER_ID))
                    self._refreshTasksToMonitor = True
                except pynng.exceptions.ConnectionRefused as ex:
                    pass

    def _sIpcPreConnectCb(self, pipe):
        addr = str(pipe.remote_address)
        if addr:
            print(f'addr: {addr} connecting to {self._routerId}')
            routerId = int(addr.split('_')[-1])
            self._ipcPipeByRouterId[routerId] = pipe
            self._refreshTasksToMonitor = True

    def _sIpcPostConnectCb(self, pipe):
        self._pipeByPipeId[pipe.id] = pipe
        addr = str(pipe.remote_address)
        if addr:
            print(f'addr: {addr} connected to {self._routerId}')

    def _sIpcPostRemoveCb(self, pipe):
        addr = str(pipe.remote_address)
        if addr:
            print(f'addr: {addr} disconnected from {self._routerId}')
            routerId = int(addr.split('_')[-1])
            self._ipcPipeByRouterId.pop(routerId, None)
            self._refreshTasksToMonitor = True

    def _sIpcHubPreConnectCb(self, pipe):
        addr = str(pipe.remote_address)
        if addr:
            routerId = int(addr.split('_')[-1])
            if routerId in self._ipcPipeByRouterId:
                raise ProgrammerError(f'Router ID {routerId} already connected to IPC hub.')
            self._ipcPipeByRouterId[routerId] = pipe
            self._refreshTasksToMonitor = True

    def _sIpcHubPostRemoveCb(self, pipe):
        addr = str(pipe.remote_address)
        if addr:
            routerId = int(addr.split('_')[-1])
            self._ipcPipeByRouterId.pop(routerId, None)
            self._refreshTasksToMonitor = True

    def newConnection(self, fn=Missing):
        return self._newConnection(next(self._connectionIdSeed), fn)

    def _newConnection(self, connectionId, fn):
        c = Connection(self, connectionId, fn)
        assert connectionId not in self._connectionById
        self._connectionById[connectionId] = c
        self._inboxById[connectionId] = asyncio.Queue()
        self._refreshTasksToMonitor = True
        return c

    def _getDirectoryAddr(self):
        return Addr(None, self._routerId, _DIRECTORY_CONNECTION_ID)

    async def shutdown(self):
        self._connectionById = {}
        self._isShuttingDown.set()
        await asyncio.sleep(0.01)  # do this here so the client doesn't have to - annoyingly we can't loop until done
        self._hasShutdown.set()
       
    @property
    def hasShutdown(self):
        return self._hasShutdown

    def _dropInboxFor(self, connectionId):
        self._inboxById.pop(connectionId, None)
        self._refreshTasksToMonitor = True

    def _route(self, msg):
        machineId, routerId, connectionId = msg.toAddr
        if machineId == machineId:
            if routerId == self._routerId:
                conn = self._connectionById.get(connectionId, Missing)
                if conn:
                    _PPMsg(f'route', msg._msgId)
                    self._inboxById[connectionId].put_nowait(msg)
                else:
                    if msg.subject == VLM.MSG_NOT_DELIVERED:
                        # don't get into a loop of undeliverable messages
                        pass
                    else:
                        reply = msg.reply(msg.toAddr, subject=VLM.MSG_NOT_DELIVERED)
                        reply._msgId = -1
                        inbox = self._inboxById.get(reply.toAddr.connectionId, Missing)
                        if inbox:
                            _PPMsg(f'unroutable', msg._msgId)
                            inbox.put_nowait(reply)
            else:
                # OPEN: handle PUB
                ipcRouterPipe = self._ipcPipeByRouterId.get(routerId, Missing)
                if ipcRouterPipe is Missing:
                    # incoming connections are on the pipe of the sIpcRouterListener
                    # outgoing connections have 1 pipe per socket

                    # I believe we can use the listening socket to dial out to other sockets
                    addr = _ipcAddr(routerId)
                    try:
                        # create an outgoing connection to the other router
                        ipcRouterPipe = self._ipcPipeByRouterId[routerId] = self._sIpc.dial(_ipcAddr(routerId))
                        self._refreshTasksToMonitor = True
                    except pynng.exceptions.ConnectionRefused as ex:
                        if msg.subject == VLM.MSG_NOT_DELIVERED:
                            # don't get into a loop of undeliverable messages
                            pass
                        else:
                            reply = msg.reply(msg.toAddr, subject=VLM.MSG_NOT_DELIVERED)
                            reply._msgId = -1
                            inbox = self._inboxById.get(reply.toAddr.connectionId, Missing)
                            if inbox:
                                _PPMsg(f'unroutable', msg._msgId)
                                inbox.put_nowait(reply)
                        return
                ipcRouterPipe.asend(stuff.encode())
        else:
            # OPEN: handle inter-machine routing
            raise NotYetImplemented('inter-machine routing')

    async def _processEventsUntilShutdown(self):
        # We keep a list of tasks waiting for events (e.g. messages to arrive in each connection's inbox.) To prevent
        # starvation we schedule them fairly by moving a task that has just been processed to the end of the list thus
        # silent tasks bubble to the front. This is mildly wasteful since silent tasks need to be checked each
        # loop but does ensure that busy tasks don't dominate things.
        taskToMonitorMap = {self._isShuttingDownTask: Monitor(_SHUTDOWN_EVENT, None)}
        running = True
        pending = []
        while running:
            if self._refreshTasksToMonitor:
                # remove old tasks that are no longer needed
                tasksToRemove = []
                for t, m in taskToMonitorMap.items():
                    if m.type == _INBOX_EVENT and m.args not in self._connectionById: tasksToRemove.append(t)   # drop closed connections
                    if m.type == _IPC_EVENT and m.args not in self._ipcPipeByRouterId: tasksToRemove.append(t)  # drop closed Ipc pipes
                for t in tasksToRemove:
                    # _PPMsg(f'dropping', f'{tasksToRemove[t]}')
                    t.cancel('no longer needed')
                    await asyncio.sleep(0)
                    # t.uncancel()    # "in cases when suppressing asyncio.CancelledError is truly desired, it is necessary to also call uncancel()"
                    taskToMonitorMap.pop(t)
                await asyncio.gather(*tasksToRemove, return_exceptions=True)
                # add new tasks that are needed
                for cId, conn in self._connectionById.items():
                    if (_INBOX_EVENT, cId) not in taskToMonitorMap.values():
                        taskToMonitorMap[asyncio.create_task(self._inboxById[cId].get())] = Monitor(_INBOX_EVENT, cId)                  # add any new connections
                for routerId, pipe in self._ipcPipeByRouterId.items():
                    if (_IPC_EVENT, routerId) not in taskToMonitorMap.values():
                        taskToMonitorMap[asyncio.create_task(self._ipcPipeByRouterId[routerId].get())] = Monitor(_IPC_EVENT, routerId)  # add any new pic pipes
                # for fnId, cb in self._scheduledCallbacksByFnId.items():
                #     if (_TIMER_EVENT, fnId) not in taskToMonitorMap.values():
                #         taskToMonitorMap[asyncio.create_task(self._ipcPipeByRouterId[routerId].get())] = Monitor(_TIMER_EVENT, fnId)  # add any new pic pipes
                self._refreshTasksToMonitor = False

            # wait for a task to complete
            done, pending = await asyncio.wait(taskToMonitorMap.keys(), return_when=asyncio.FIRST_COMPLETED)

            # process it
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
                        asyncio.create_task(conn._deliver(msg))
                        # add a new task for this connection to the end of the queue
                        taskToMonitorMap[asyncio.create_task(inbox.get())] = m
                elif m.type == _IPC_EVENT:
                    routerId = m.args
                    raw = task.result()
                    msg = _msgFromBytes(raw)
                    # route the message
                    self._route(msg)
                    # add a new task for this pipe to the end of the queue
                    pipe = self._ipcPipeByRouterId[routerId]
                    taskToMonitorMap[asyncio.create_task(pipe.get())] = m
                elif m.type == _TCP_EVENT:
                    raise NotYetImplemented('_TCP_EVENT')
                elif m.type == _TIMER_EVENT:
                    fnId = m.args
                    raise NotYetImplemented('_TIMER_EVENT')
                    taskToMonitorMap[asyncio.create_task(inbox.get())] = m
                else:
                    raise ProgrammerError(f'Unknown monitor type "{m.type}".')


        for t in pending:
            t.cancel()
            await asyncio.sleep(0)
        for t in taskToMonitorMap.keys():
            t.cancel()
            await asyncio.sleep(0)
        _PPMsg('shutdown', '')



# **********************************************************************************************************************
# Directory
# **********************************************************************************************************************

class Directory:
    # OPEN: add security so agents can only add / remove their own entries and see only what they are allowed to see,
    #       but what about telling a directory that a connection didn't get delivered
    __slots__ = (
        '_conn',
        '_entries',                 # [Entry]
        '_removeIfNoPingReply',     # map of addr -> timestamp
        '_heartbeatEntriesTimeout',
    )

    def __init__(self, router, noDrop=False, heartbeatEntriesTimeout=Missing):
        if router._connectionById.get(_DIRECTORY_CONNECTION_ID, Missing) is not Missing:
            raise RuntimeError('A Directory already exists on this router')
        self._conn = router._newConnection(_DIRECTORY_CONNECTION_ID, self.msgArrived)
        self._heartbeatEntriesTimeout = _DEFAULT_HEARTBEAT_ENTRIES_TIMEOUT if heartbeatEntriesTimeout is Missing else heartbeatEntriesTimeout
        if not noDrop:
            router.scheduleCallback(self._heartbeatEntries, every=self._heartbeatEntriesTimeout)
        self._entries = []
        self._removeIfNoPingReply = set()

    async def msgArrived(self, msg):
        # self._removeIfNoPingReply.discard(msg.fromAddr)

        if msg.subject == VLM.REGISTER_ENTRY:
            # OPEN: use this instead of a heartbeat
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

        elif msg.subject == VLM.PING:
            if not msg.isReply: await self._conn.send(msg.reply(None))

        else:
            await self._conn.send(msg.reply(msg.subject, subject=VLM.DOES_NOT_UNDERSTAND))

    def _heartbeatEntries(self):
        self._entries = [entry for entry in self._entries if entry.addr not in self._removeIfNoPingReply]
        self._removeIfNoPingReply = set([entry.addr for entry in self._entries])
        for addr in self._removeIfNoPingReply:
            asyncio.create_task(self._conn.send(Msg(addr, VLM.PING, None)))



# **********************************************************************************************************************
# Serialization
# **********************************************************************************************************************

def _msgAsBytes(msg):
    bytes = io.BytesIO()
    simpleion.dump('1', bytes, binary=True)
    simpleion.dump(msg.fromAddr.routerId, bytes, binary=True)
    simpleion.dump(msg.fromAddr.connectionId, bytes, binary=True)
    if msg.toAddr == VLM.PUB:
        simpleion.dump(None, bytes, binary=True)
        simpleion.dump(None, bytes, binary=True)
    else:
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
        msg = Msg(VLM.PUB, subject, contents)
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
