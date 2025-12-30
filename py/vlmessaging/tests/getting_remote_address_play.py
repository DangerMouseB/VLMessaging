# **********************************************************************************************************************
# Copyright 2025 David Briant, https://github.com/coppertop-bones. Licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License. You may obtain a copy of the  License at
# http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY  KIND,
# either express or implied. See the License for the specific language governing permissions and limitations under the
# License. See the NOTICE file distributed with this work for additional information regarding copyright ownership.
# **********************************************************************************************************************

# to establish the identity of the remote peer connected to a pipe

# Python imports
import argparse, pynng, asyncio, os

# VLMessaging imports
from vlmessaging.utils.co import until


class Router:

    __slots__ = ('_sock', 'addr', 'mEp', '_pipeByPipeId', '_pipeIdByRouterId', '_mEpByPipeId', 'running')

    def __init__(self, listen_addr, *connect_addrs):
        self.mEp = os.getpid()
        self._pipeByPipeId = {}
        self._pipeIdByRouterId = {}
        self._mEpByPipeId = {}

        self._sock = pynng.Pair1(polyamorous=True)
        self._sock.add_post_pipe_connect_cb(self.post_connect_cb)
        self._sock.add_post_pipe_remove_cb(self.post_remove_cb)
        listener = self._sock.listen(listen_addr)
        extra = f' and connecting to {", ".join(connect_addrs)}' if connect_addrs else ''
        print(f'\n\n<{self.mEp}> listening on {str(listener.local_address)}{extra}')
        for addr in connect_addrs:
            dialer = self._sock.dial(addr)
        self.running = True
        asyncio.create_task(self.recv_eternally())
        asyncio.create_task(self.send_eternally())

    def post_connect_cb(self, pipe):
        try:
            # send my router id to the remote peer as the first message on this pipe
            pipe.socket.send(str(self.mEp).encode(), block=False)
        except Exception as ex:
            print(repr(ex))
        self._pipeByPipeId[pipe.id] = pipe
        print(f'post_connect_cb: <{pipe.remote_address}::{pipe.id}>')

    def post_remove_cb(self, pipe):
        mEp = self._mEpByPipeId.get(pipe.id, None)
        if mEp:
            self._mEpByPipeId.pop(pipe.id, None)
            self._pipeIdByRouterId.pop(mEp, None)
            print(f'disconnected: <{mEp}> aka <{pipe.remote_address}::{pipe.id}>')
        else:
            print(f'disconnected: <{pipe.local_address}::{pipe.id}>')
        self._pipeByPipeId.pop(pipe.id, None)

    async def send_eternally(self):
        while self.running:
            stuff = await asyncio.to_thread(input)
            if stuff == 'quit':
                self.running = False
                await self._sock.close()
            for pipe in self._sock.pipes:
                mEp = self._mEpByPipeId[pipe.id]
                print(f'Sending "{stuff}" to <{mEp}> aka <{pipe.remote_address}::{pipe.id}>')
                await pipe.asend(stuff.encode())

    async def recv_eternally(self):
        while self.running:
            msg = await self._sock.arecv_msg()
            pipeId = msg.pipe.id
            content = msg.bytes.decode()
            mEp = self._mEpByPipeId.get(pipeId, None)
            if mEp is None:
                # first message from the remote peer on this pipe is its mEp
                mEp = int(content)
                self._mEpByPipeId[pipeId] = mEp
                self._pipeIdByRouterId[mEp] = pipeId
                print(f'resolved: <{msg.pipe.local_address}::{pipeId}> to <{mEp}>')
            else:
                print(f'<{mEp}> aka <{msg.pipe.remote_address}::{pipeId}> says: "{content}"')


async def main():
    if os.environ.get('PYCHARM', None):
        listenOn = 'ipc:///tmp/fred'
        connectTo = ['ipc:///tmp/sally']
        # connectTo = []
    else:
        try:
            p = argparse.ArgumentParser(description=__doc__)
            p.add_argument(
                "listenOn",
                help="Address to listen; e.g. tcp://127.0.0.1:13134",
            )
            p.add_argument(
                "connectTo",
                nargs='*',
                help="Address to dial; e.g. tcp://127.0.0.1:13134",
            )
            args = p.parse_args()
            listenOn = args.listenOn
            connectTo = args.connectTo
        except:
            listenOn = input()
            connectTo = input()
            listenOn = f'ipc:///tmp/{listenOn}'
            connectTo = f'ipc:///tmp/{connectTo}'

    r = Router(listenOn, connectTo)
    await until(r.shutdown)
    print('done')



if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
