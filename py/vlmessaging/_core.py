# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************


# Router is responsible for routing messages between local connections and / or other routers in other local and / or
# remote. Local routing does not require serialisation, cross process / cross machine routing does.
# if nng's ipc transport is faster than its tcp transport then the router should use it in the background

# if we want this router to publish agents in the directory then it must have two listener sockets, one (ipc based) for
# local agents from this smachine, and another (tcp based) for remote agents on other machines. These sockets can be
# created lazily whenever an agent advertises itself. The local directory name shall be "ipc:///tmp/local_dir.ipc"

# threading design
# each daemon with a connection is on its own thread - so preemptive (albeit single threaded at the interpreter level)
# we want the router itself to be non-blocking so use Python's async methods
# we may put resource discovery into the router thread
# pubsub will be sent via a socket rather than locally


import itertools as _itertools
from io import BytesIO as _BytesIO
from amazon.ion import simpleion as _simpleion

from coppertop.utils import Missing, NotYetImplemented

from vlmessaging._structs import Addr, Msg, Entry

PUB = None
LOCAL_DIRECTORY = Addr('LOCAL_DIRECTORY', -1)
REMOTE_DIRECTORY = Addr('REMOTE_DIRECTORY', -1)


INVALID_ADDRESS = 'INVALID_ADDRESS'
REGISTER_SERVICE = 'REGISTER_SERVICE'
REGISTER_SERVICE_REPLY = 'REGISTER_SERVICE_REPLY'
UNREGISTER_SERVICE = 'UNREGISTER_SERVICE'
UNREGISTER_SERVICE_REPLY = 'UNREGISTER_SERVICE_REPLY'
GET_ENTRIES = 'GET_ENTRIES'
GET_ENTRIES_REPLY = 'GET_ENTRIES_REPLY'
HEARTBEAT = 'HEARTBEAT'
HEARTBEAT_REPLY = 'HEARTBEAT_REPLY'


class Connection:
    __slots__ = ('connectionId', 'router', '_msgIdSeed', '_fromAddr')
    def __init__(self, router, connectionId):
        self.connectionId = connectionId
        self.router = router
        self._msgIdSeed = _itertools.count(1)
        self._fromAddr = Addr(router.socketAddr, connectionId)
    def send(self, msg, timeout) -> Msg | Missing:
        msg.fromAddr = self._fromAddr
        msg._msgIdSeed = next(self._msgIdSeed)
        return self.router.send(msg, timeout)
    @property
    def addr(self):
        return self._fromAddr



class Router:

    __slots__ = ('socket', 'connectionIdSeed', 'socketAddr', 'connectionsById', '_localDirSocket')

    def __init__(self):
        self.socket = Missing
        self.connectionIdSeed = _itertools.count(1)
        self.socketAddr = Missing
        self.connectionsById = {}

    def newConnection(self) -> Connection:
        connId = next(self.connectionIdSeed)
        answer = Connection(self, connId)
        self.connectionsById[connId] = answer
        return answer

    def _send(self, msg, timeout=Missing) -> Msg | Missing:
        # if timeout is Missing send asynchronously
        if msg.toAddr == PUB:
            # broadcast on the connection's pubsub socket
            raise NotYetImplemented()
        else:
            if msg.toAddr.socketAddr == LOCAL_DIRECTORY:
                if not self._localDirSocket:
                    # try connecting to local dir
                    # if can't be dialled try creating local directory
                    raise NotYetImplemented()
                raise NotYetImplemented()
            raise NotYetImplemented()



def _msgAsBytes(msg):
    bytes = _BytesIO()
    _simpleion.dump('1', bytes, binary=True)
    _simpleion.dump(msg.fromAddr.socketAddr, bytes, binary=True)
    _simpleion.dump(msg.fromAddr.connId, bytes, binary=True)
    if msg.toAddr == PUB:
        _simpleion.dump(None, bytes, binary=True)
        _simpleion.dump(None, bytes, binary=True)
    else:
        _simpleion.dump(msg.toAddr.socketAddr, bytes, binary=True)
        _simpleion.dump(msg.toAddr.connId, bytes, binary=True)
    _simpleion.dump(msg.subject, bytes, binary=True)
    _simpleion.dump(msg._msgId, bytes, binary=True)
    _simpleion.dump(msg._replyId, bytes, binary=True)
    _simpleion.dump(msg.contents, bytes, binary=True)
    _simpleion.dump(msg.meta, bytes, binary=True)
    return bytes.getvalue()

def _msgFromBytes(bytes):
    values = _simpleion.load(_BytesIO(bytes), single_value=False)
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
        msg = Msg(Addr(toAddrSocketAddr, toAddrConnId), subject, contents)
    else:
        msg = Msg(PUB, subject, contents)
    msg.fromAddr = Addr(fromAddrSocketAddr, fromAddrConnId)
    msg._msgId = _msgId
    msg._replyId = _replyId
    msg.meta = meta
    # OPEN: assert stream at end
    return msg




