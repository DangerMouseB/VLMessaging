# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# Python imports
import time

# 3rd party imports
from coppertop.utils import Missing

# local imports
from vlmessaging import Msg, Entry, VLM


class PingPongAgent:

    __slots__ = ('conn', 'running')

    ENTRY_TYPE = 'PingPongAgent'
    PING = 'PING'
    PONG = 'PONG'
    DO_IT = 'DO_IT'
    DO_IT_PROGRESS = 'DO_IT_PROGRESS'
    SHUTDOWN = 'SHUTDOWN'

    def __init__(self, router):
        self.conn = router.newConnection(self.msgArrived)

    async def register(self):
        entryAdded = False
        while not entryAdded:
            msg = Msg(Addr(None, None, VLM.DIRECTORY), VLM.REGISTER_ENTRY, Entry(self.conn.addr, self.ENTRY_TYPE, None, None, None))
            entryAdded = await self.conn.send(msg, 1000)
            if entryAdded: entryAdded = entryAdded.contents

    async def msgArrived(self, msg):

        if msg.subject == self.DO_IT:
            contents = {'msg': msg, 'N': msg.contents, 'i': 0, 't1': time.perf_counter_ns()}
            m = Msg(Addr(None, None, VLM.DIRECTORY), VLM.GET_ENTRIES, self.ENTRY_TYPE)
            res = await self.conn.send(m, 1000)
            for e in res.contents:
                if e.addr != self.conn.addr:
                    toAddr = e.addr
                    break
            await self.conn.send(Msg(toAddr, self.PING, contents))
            await self.conn.send(Msg(msg.fromAddr, self.DO_IT_PROGRESS, "Started"))

        elif msg.subject in (self.PING, self.PONG):
            contents = msg.contents
            contents['n'] += 1
            if contents['n'] >= contents['N']:
                contents['t2'] = time.perf_counter_ns()
                reply = contents['msg'].reply(contents)
                await self.conn.send(reply)
            else:
                reply = Msg(msg.replyTo, self.PONG if msg.subject == self.PING else self.PING, contents)
                await self.conn.send(reply)

        elif msg.subject == self.SHUTDOWN:
            self.running = False

        elif msg.subject == VLM.MSG_NOT_DELIVERED:
            if msg.contents == self.getCurrentAddr:
                await self.conn.send(Msg(Addr(None, None, VLM.DIRECTORY), VLM.UNREGISTER_ADDR, self.getCurrentAddr))
                self.getCurrentAddr = Missing   # force a rediscovery next time

        else:
            return [VLM.IGNORE_UNHANDLED_REPLIES, VLM.HANDLE_DOES_NOT_UNDERSTAND]
