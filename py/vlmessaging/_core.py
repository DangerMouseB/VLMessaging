# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************


# Python imports
import itertools, logging, pynng, asyncio, weakref, collections, io, os
from amazon.ion import simpleion

# coppertop imports
from coppertop.utils import Missing, NotYetImplemented, ProgrammerError

# local imports
from vlmessaging import _constants as VLM


_logger = logging.getLogger(__name__)


_DIRECTORY_CONNECTION_ID = 1
_FIRST_CONNECTION_ID = _DIRECTORY_CONNECTION_ID + 1

_MACHINE_HUB_DIRECTORY_ADDR = "ipc:///tmp/agent_0"

# _AGENT_ADDR_PREFIX = "ipc:///tmp/agent_<pid>"
# X_MACHINE_LISTEN_PORT = "tcp://127.0.0.1:13134"




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
                reply = await asyncio.wait_for(fut, timeout / 1000)
            except asyncio.TimeoutError:
                _PPMsg(f'TIMED OUT', msg)
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



# **********************************************************************************************************************
# Router
# **********************************************************************************************************************

class Router:

    __slots__ = (
        '_sDirectoryListener', '_sDirectory',                           # local directory connections
        '_sLocalPeerListener', '_localPipeByAddr', '_sLocalByAddr',     # local peer connections
        '_sRemotePeerListener', '_remotePipeByAddr', '_sRemoteByAddr',  # remote peer connections
        '_routerId', '_connectionIdSeed', '_connectionById', '_inboxById',
        '_refreshInboxTasks',
        '_closingDown', '_hasShutdown',
    )

    def __init__(self):
        self._sDirectoryListener, self._sDirectory = Missing, Missing
        self._sLocalPeerListener, self._localPipeByAddr, self._sLocalByAddr = Missing, {}, {}
        self._sRemotePeerListener, self._remotePipeByAddr, self._sRemoteByAddr = Missing, {}, Missing
        self._connectionById , self._inboxById = weakref.WeakValueDictionary(), {}
        self._connectionIdSeed, self._refreshInboxTasks = itertools.count(_FIRST_CONNECTION_ID), False
        asyncio.create_task(self._processInboxes())
        self._closingDown = asyncio.Event()
        self._hasShutdown = asyncio.Event()
        self._routerId = os.getpid()

        # mode
        # - VLM.LOCAL_MODE
        #   - starts local directory
        # - VLM.MACHINE_MODE
        #   - additionally will attempt to find machine hub directory - every x milliseconds, e.g. 1000
        #   - will listen for local machine peers
        # - VLM.NETWORK_MODE - additionally will attempt to find network hub directories
        #   - will listen for remote machine peers only if an agent advertises itself on a network hub directory
        # canStartMachineHubDirectory
        #   - will attempt to start local machine hub directory if none found, which involves listening on
        #     _MACHINE_HUB_DIRECTORY_ADDR
        # networkHubDirectoryPorts = [30000, 30001, 30002] - attempts to listen on port every x milliseconds
        #   - adds network hub directory to machine hub directory and own directory and forwards messages from the port
        #     to the network hub directory
        # isIntraMachineRouter - allows forwarding of messages between other machine routers and network routers

    def newConnection(self, fn=Missing):
        return self._newConnection(next(self._connectionIdSeed), fn)

    def _newConnection(self, connectionId, fn):
        c = Connection(self, connectionId, fn)
        assert connectionId not in self._connectionById
        self._connectionById[connectionId] = c
        self._inboxById[connectionId] = asyncio.Queue()
        self._refreshInboxTasks = True
        return c

    def _getDirectoryAddr(self):
        return Addr(None, self._routerId, _DIRECTORY_CONNECTION_ID)

    async def shutdown(self):
        self._connectionById = {}
        self._closingDown.set()
        await asyncio.sleep(0.01)  # do this here so the client doesn't have to - annoyingly we can't loop until done
        self._hasShutdown.set()

    async def hasShutdown(self):
        await self._hasShutdown.wait()

    def _dropInboxFor(self, connectionId):
        self._inboxById.pop(connectionId, None)
        self._refreshInboxTasks = True

    def _route(self, msg):
        machineId, routerId, connectionId = msg.toAddr
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
            raise NotYetImplemented(f'inter-router routing to router {routerId}')

    async def _processInboxes(self):
        # We keep a list of tasks waiting for messages to arrive in each connection's inbox. To prevent starvation we
        # schedule them fairly by moving a connection's task that has just been processed to the end of the list thus
        # silent connections bubble to the front. This is mildly wasteful since silent tasks need to be checked each
        # loop but does ensure that busy connections don't dominate.
        tasks = {asyncio.create_task(self._closingDown.wait()): -2}
        running = True
        pending = []
        while running:
            if self._connectionById:
                if self._refreshInboxTasks:
                    # drop any tasks for closed connections
                    tasksToRemove = {t: cId for t, cId in tasks.items() if cId not in self._connectionById and cId > 0}
                    for t in tasksToRemove:
                        # _PPMsg(f'dropping', f'{tasksToRemove[t]}')
                        t.cancel('no longer needed')
                        await asyncio.sleep(0)
                        # t.uncancel()    # "in cases when suppressing asyncio.CancelledError is truly desired, it is necessary to also call uncancel()"
                        tasks.pop(t)
                    await asyncio.gather(*tasksToRemove, return_exceptions=True)
                    # add any new connections
                    for cId, conn in self._connectionById.items():
                        if cId not in tasks.values():
                            tasks[asyncio.create_task(self._inboxById[cId].get())] = cId
                    self._refreshInboxTasks = False
                # wait for one of the tasks to complete
                done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    # pull the done task from the queue
                    connectionId = tasks.pop(task)
                    if connectionId == -2: running = False
                    msg = task.result()
                    if (conn := self._connectionById.get(connectionId, Missing)) is not Missing:
                        inbox = self._inboxById[connectionId]
                        asyncio.create_task(conn._deliver(msg))
                        # add a new task for this connection to the end of the queue
                        tasks[asyncio.create_task(inbox.get())] = connectionId
            else:
                #  sleep briefly and try again
                await asyncio.sleep(0)
        for t in pending:
            t.cancel()
            await asyncio.sleep(0)
        for t in tasks:
            t.cancel()
            await asyncio.sleep(0)
        _PPMsg('shutdown', '')



# **********************************************************************************************************************
# Directory
# **********************************************************************************************************************

class Directory:

    __slots__ = ('_conn', '_entries')

    def __init__(self, router, *args, **kwargs):
        if router._connectionById.get(_DIRECTORY_CONNECTION_ID, Missing) is not Missing: raise RuntimeError('A Directory already exists on this router')
        self._conn = router._newConnection(_DIRECTORY_CONNECTION_ID, self.msgArrived)
        self._entries = []

    async def msgArrived(self, msg):

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

        elif msg.subject == VLM.HEARTBEAT:
            # OPEN: should check that a given entry exists
            await self._conn.send(msg.reply(None))

        else:
            await self._conn.send(msg.reply(msg.subject, subject=VLM.DOES_NOT_UNDERSTAND))


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
