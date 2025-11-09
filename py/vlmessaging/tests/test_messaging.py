# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# Python imports
import asyncio

# local imports
from vlmessaging import Msg, Addr, Router, VLM
from vlmessaging._core import _msgFromBytes, _msgAsBytes


def test_serialise():
    msg = Msg(Addr(None, None, 3), 'TEST', dict(hello='world'))
    msg.fromAddr = Addr(None, 1, 2)
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


def test_messaging():

    # test that sending to a non-existent connection returns MSG_NOT_DELIVERED
    # test that unawaited sending to a connection with no handler returns MSG_NOT_DELIVERED
    # test that awaited sending to a connection with no handler gets handled as a reply
    # test that dropped connections are cleaned up properly
    # test VLM.IGNORE_UNHANDLED_REPLIES
    # test VLM.HANDLE_DOES_NOT_UNDERSTAND

    # msg = Msg(toAddr, "FRED", None)
    # res = await conn.send(msg, 5000)

    async def run_add_one_test():
        router = Router()
        x1 = router.newConnection()
        x2 = router.newConnection(lambda m: None)

        result1 = await conn.send(Msg(conn.addr, 'GET_FRED', None), 5000)
        if result1:
            _PPMsg(f'Got', f'{result1.subject} = {result1.contents}')
        else:
            print('Timedout waiting for a result')
        x1 = x2 = None

        result2 = await conn.send(Msg(conn.addr, 'ADD_ONE_TO_CURRENT', None), 5000)

        if result2:
            _PPMsg(f'Got', f'{result2.subject} = {result2.contents}')
        else:
            print('Timedout waiting for a result')

        await router.shutdown()

        return f'{result1.subject} = {result1.contents}', result2.contents

    result1, result2 = asyncio.run(run_add_one_test())
    assert result1 == 'DOES_NOT_UNDERSTAND = GET_FRED'
    assert result2 == 42


def main():
    test_serialise()
    # test_messaging() - wip
    print('passed')


if __name__ == '__main__':
    main()
