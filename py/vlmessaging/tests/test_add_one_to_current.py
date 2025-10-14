# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

import asyncio

from coppertop.utils import Missing

from vlmessaging import Msg, Router, UNKNOWN_SUBJECT
from vlmessaging._core import printMsg


class AddOneQueuingDaemon:

    def __init__(self, router):
        self.conn = router.newConnection(self.msgArrived)
        self.wait = 500

    async def msgArrived(self, msg):

        if msg.subject == 'ADD_ONE_TO_CURRENT':
            current = Missing
            while not current:
                current = await self.conn.send(Msg(self.conn._addr, 'GET_CURRENT', Missing), 200)
            await self.conn.send( msg.reply('ADD_ONE_TO_CURRENT_REPLY', current.contents + 1) )

        elif msg.subject == 'GET_CURRENT':
            await asyncio.sleep(self.wait / 1000)
            self.wait -= 100
            await self.conn.send( msg.reply('GET_CURRENT_REPLY', 41) )

        elif msg.subject in ('GET_CURRENT_REPLY', 'ADD_ONE_TO_CURRENT_REPLY'):
            pass

        else:
            await self.conn.send(msg.reply(UNKNOWN_SUBJECT, msg.subject))



def test_add_one_to_current():

    async def run_add_one_test():
        router = Router()
        daemon = AddOneQueuingDaemon(router)
        conn = daemon.conn
        result1 = await conn.send(Msg(conn._addr, 'GET_FRED', None), 5000)
        if result1:
            printMsg(f'Got', f'{result1.subject} = {result1.contents}')
        else:
            print('Timedout waiting for a result')

        result2 = await conn.send(Msg(conn._addr, 'ADD_ONE_TO_CURRENT', None), 5000)

        if result2:
            printMsg(f'Got', f'{result2.subject} = {result2.contents}')
        else:
            print('Timedout waiting for a result')

        return f'{result1.subject} = {result1.contents}', result2.contents


    result1, result2 = asyncio.run(run_add_one_test())
    assert result1 == 'UNKNOWN_SUBJECT = GET_FRED'
    assert result2 == 42



if __name__ == '__main__':
    test_add_one_to_current()
    print('passed')
