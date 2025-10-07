# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

from coppertop.utils import Missing

import vlmessaging as vlm
from vlmessaging import Msg, Addr, Entry, LOCAL_DIRECTORY, REGISTER_SERVICE, HEARTBEAT, HEARTBEAT_REPLY, GET_ENTRIES
from vlmessaging._core import _msgFromBytes, _msgAsBytes



def test_msg():
    msg = Msg(Addr('local', 1), 'TEST', dict(hello='world'))
    msg.fromAddr = Addr('local', 2)
    msg._msgId = 1
    bytes = _msgAsBytes(msg)
    msg2 = _msgFromBytes(bytes)
    msg2.contents = dict(msg2.contents)
    msg2.meta = dict(msg2.meta)
    assert msg.toAddr == msg2.toAddr
    assert msg.fromAddr == msg2.fromAddr
    assert msg.subject == msg2.subject
    assert msg._msgId == msg2._msgId
    assert msg._replyId == msg2._replyId



class AddOneDaemon:
    __slots__ = ('conn')
    def __init__(self, conn):
        self.conn = conn
        conn.handler = self.msgArrived
    def register(self):
        self.conn.send(Msg(LOCAL_DIRECTORY, REGISTER_SERVICE, Entry(self.conn.addr, 'ADD_ONE', None)))
    def msgArrived(self, msg):
        if msg.subject == 'ADD_ONE':
            answer = msg.contents + 1
            reply = msg.reply('ADD_ONE_REPLY', answer)
            self.conn.send(reply)
        elif msg.subject == HEARTBEAT:
            reply = msg.reply(HEARTBEAT_REPLY, None)
            self.conn.send(reply)



def test_addOne():
    router = vlm.Router()
    daemon = AddOneDaemon(router.newConnection())
    daemon.register()

    conn = router.newConnection()

    # find the AddOneDaemon
    msg = Msg(Addr(router.socketAddr, daemon.conn.connectionId), GET_ENTRIES, None)
    reply = conn.send(msg, 1000)
    assert reply
    addOneAddr = Missing
    for addr, service, params in reply.contents:
        if service == 'ADD_ONE':
            addOneAddr = addr
            break
    assert addOneAddr

    # get the daemon to add one
    msg = Msg(addOneAddr, 'ADD_ONE', 1)
    reply = conn.sendMsg(msg, 1000)
    assert reply.contents == 2



def main():
    test_msg()
    test_addOne()
    print('passed')


if __name__ == '__main__':
    main()
