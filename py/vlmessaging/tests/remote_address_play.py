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
import argparse, pynng, trio
import os

try:
    run_sync = trio.to_thread.run_sync
except AttributeError:
    # versions of trio prior to 0.12.0 used this method
    run_sync = trio.run_sync_in_worker_thread


class Router:

    __slots__ = ('_n', '_sock', 'addr', 'routerId', '_pipeByPipeId', '_pipeIdByRouterId', '_routerIdByPipeId', 'running')

    def __init__(self, n, listen_addr, *connect_addrs):
        self._n = n
        self.routerId = os.getpid()
        self._pipeByPipeId = {}
        self._pipeIdByRouterId = {}
        self._routerIdByPipeId = {}

        self._sock = pynng.Pair1(polyamorous=True)
        self._sock.add_pre_pipe_connect_cb(self.pre_connect_cb)
        self._sock.add_post_pipe_connect_cb(self.post_connect_cb)
        self._sock.add_post_pipe_remove_cb(self.post_remove_cb)
        listener = self._sock.listen(listen_addr)
        extra = f' and connecting to {", ".join(connect_addrs)}' if connect_addrs else ''
        print(f'\n\n<{self.routerId}> listening on {str(listener.local_address)}{extra}')
        for addr in connect_addrs:
            dialer = self._sock.dial(addr)
        self.running = True
        n.start_soon(self.recv_eternally, self._sock)
        n.start_soon(self.send_eternally, self._sock)

    def pre_connect_cb(self, pipe):
        # in ipc local_address and remote_address are the same string - so display pipe id to distinguish remote peers
        print(f'pre_connect_cb: <{pipe.remote_address}::{pipe.id}>')

    def post_connect_cb(self, pipe):
        try:
            # send my router id to the remote peer as the first message on this pipe
            msg = pynng.Message(str(self.routerId).encode(), pipe)
            self._sock.send_msg(msg, block=False)
        except Exception as ex:
            print(repr(ex))
        self._pipeByPipeId[pipe.id] = pipe
        print(f'post_connect_cb: <{pipe.remote_address}::{pipe.id}>')

    def post_remove_cb(self, pipe):
        routerId = self._routerIdByPipeId.get(pipe.id, None)
        if routerId:
            self._routerIdByPipeId.pop(pipe.id, None)
            self._pipeIdByRouterId.pop(routerId, None)
            print(f'disconnected: <{routerId}> aka <{pipe.remote_address}::{pipe.id}>')
        else:
            print(f'disconnected: <{pipe.local_address}::{pipe.id}>')
        self._pipeByPipeId.pop(pipe.id, None)

    async def send_eternally(self, sock):
        while self.running:
            stuff = await run_sync(input)
            if stuff == 'quit':
                self.running = False
                await self._sock.close()
            for pipe in sock.pipes:
                routerId = self._routerIdByPipeId[pipe.id]
                print(f'Sending "{stuff}" to <{routerId}> aka <{pipe.remote_address}::{pipe.id}>')
                await pipe.asend(stuff.encode())

    async def recv_eternally(self, sock):
        while self.running:
            msg = await sock.arecv_msg()
            pipeId = msg.pipe.id
            content = msg.bytes.decode()
            routerId = self._routerIdByPipeId.get(pipeId, None)
            if routerId is None:
                # first message from the remote peer on this pipe is its routerId
                routerId = int(content)
                self._routerIdByPipeId[pipeId] = routerId
                self._pipeIdByRouterId[routerId] = pipeId
                print(f'resolved: <{msg.pipe.local_address}::{pipeId}> to <{routerId}>')
            else:
                print(f'<{routerId}> aka <{msg.pipe.remote_address}::{pipeId}> says: "{content}"')


async def main():
    if os.environ.get('PYCHARM', None):
        listenOn = 'ipc:///tmp/fred'
        connectTo = ['ipc:///tmp/sally']
        # connectTo = []
    else:
        p = argparse.ArgumentParser(description=__doc__)
        p.add_argument(
            "listenOn",
            help="Address to listen or dial; e.g. tcp://127.0.0.1:13134",
        )
        p.add_argument(
            "connectTo",
            nargs='*',
            help="Address to listen or dial; e.g. tcp://127.0.0.1:13134",
        )
        args = p.parse_args()
        listenOn = args.listenOn
        connectTo = args.connectTo

    async with trio.open_nursery() as n:
        l = Router(n, listenOn, *connectTo)



if __name__ == "__main__":
    try:
        trio.run(main)
    except KeyboardInterrupt:
        pass
