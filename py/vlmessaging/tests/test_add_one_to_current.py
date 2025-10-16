# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# Python imports
import asyncio, multiprocessing, os

# 3rd party imports
from coppertop.utils import Missing

# local imports
from vlmessaging import Msg, Router, Entry, Directory, VLM
from vlmessaging.utils import _findSingleEntryOfTypeOrExit, _PPMsg, with_async_init


@with_async_init
class GetCurrentAgent:

    __slots__ = ('conn', 'wait')

    ENTRY_TYPE = 'GetCurrentAgent'
    GET_CURRENT = 'GET_CURRENT'
    GET_CURRENT_REPLY = 'GET_CURRENT_REPLY'

    async def __init__(self, router, wait):
        self.conn = router.newConnection(self.msgArrived)
        self.wait = wait
        entryAdded = False
        while not entryAdded:
            msg = Msg(VLM.DIRECTORY, VLM.REGISTER_ENTRY, Entry(self.conn.addr, self.ENTRY_TYPE, None))
            entryAdded = await self.conn.send(msg, 1000)
            if entryAdded: entryAdded = entryAdded.contents

    async def msgArrived(self, msg):

        if msg.subject == self.GET_CURRENT:
            await asyncio.sleep(self.wait / 1000)
            self.wait = max(0, self.wait - 100)
            await self.conn.send( msg.reply(self.GET_CURRENT_REPLY, 41) )

        else:
            return [VLM.IGNORE_UNHANDLED_REPLIES, VLM.HANDLE_DOES_NOT_UNDERSTAND]


@with_async_init
class AddOneToCurrentAgent:

    __slots__ = ('conn', 'addrOfGetCurrentAgent')

    ENTRY_TYPE = 'AddOneToCurrentAgent'
    ADD_ONE_TO_CURRENT = 'ADD_ONE_TO_CURRENT'
    ADD_ONE_TO_CURRENT_REPLY = 'ADD_ONE_TO_CURRENT_REPLY'

    async def __init__(self, router):
        self.conn = router.newConnection(self.msgArrived)
        self.addrOfGetCurrentAgent = Missing
        entryAdded = False
        while not entryAdded:
            msg = Msg(VLM.DIRECTORY, VLM.REGISTER_ENTRY, Entry(self.conn.addr, self.ENTRY_TYPE, None))
            entryAdded = await self.conn.send(msg, 1000)
            if entryAdded: entryAdded = entryAdded.contents


    async def msgArrived(self, msg):

        if msg.subject == self.ADD_ONE_TO_CURRENT:
            errMsg = msg.reply(self.ADD_ONE_TO_CURRENT_REPLY, RuntimeError(f'Can\'t find a {GetCurrentAgent.ENTRY_TYPE}'))
            current = Missing
            while not current:
                if self.addrOfGetCurrentAgent is Missing:
                    self.addrOfGetCurrentAgent = await _findSingleEntryOfTypeOrExit(self.conn, GetCurrentAgent.ENTRY_TYPE, 1000, errMsg)
                current = await self.conn.send(Msg(self.addrOfGetCurrentAgent, GetCurrentAgent.GET_CURRENT, Missing), 200)
            reply = msg.reply(self.ADD_ONE_TO_CURRENT_REPLY, current.contents + 1)
            await self.conn.send(reply)

        elif msg.subject == VLM.MSG_NOT_DELIVERED:
            if msg.contents == self.addrOfGetCurrentAgent:
                await self.conn.send(Msg(VLM.DIRECTORY, VLM.UNREGISTER_ADDR, self.addrOfGetCurrentAgent))
                self.addrOfGetCurrentAgent = Missing   # force a rediscovery next time

        else:
            return [VLM.IGNORE_UNHANDLED_REPLIES, VLM.HANDLE_DOES_NOT_UNDERSTAND]



def test_add_one_to_current():

    async def run_add_one_test():
        router = Router()
        directory = Directory(router, VLM.LOCAL)
        addOneAgent = await AddOneToCurrentAgent(router)
        getCurrentAgent = await GetCurrentAgent(router, 500)
        conn = router.newConnection()

        # check that AddOneToCurrentAgent can find GetCurrentAgent and get a reply eventually
        toAddr = addOneAgent.conn.addr          # cheat instead of getting address from directory
        msg = Msg(toAddr, AddOneToCurrentAgent.ADD_ONE_TO_CURRENT, None)
        res = await conn.send(msg, 5000)
        _PPMsg(f'Got', f'{res.subject} = {res.contents}')

        # kill off the GetCurrentAgent to test that the AddOneToCurrentAgent copes
        getCurrentAgent.conn = None
        getCurrentAgent = None
        await asyncio.sleep(0.01)

        # start a new GetCurrentAgent
        getCurrentAgent = await GetCurrentAgent(router, 0)

        # test resilience of AddOneToCurrentAgent
        toAddr = addOneAgent.conn.addr          # ditto
        msg = Msg(addOneAgent.conn.addr, AddOneToCurrentAgent.ADD_ONE_TO_CURRENT, None)
        res = await conn.send(msg, 5000)
        _PPMsg(f'Got', f'{res.subject} = {res.contents}')

        await router.shutdown()
        return res.contents

    res = asyncio.run(run_add_one_test())
    assert res == 42


def run_in_subprocess():
    p = multiprocessing.Process(target=test_add_one_to_current)
    p.start()
    p.join()
    print(f'parentid: {os.getpid()}, childid: {p.pid}')



if __name__ == "__main__":
    run_in_subprocess()
    print('passed')
