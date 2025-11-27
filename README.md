# VL-MESSAGING - Very Light Messaging #


## SUMMARY ##

VLMessaging is intended as an easy to use lightweight peer-to-peer messaging system that can route messages between 
agents living in the same thread, and between threads, processes and machines. It provides a failure robust 
responsibility oriented directory service for resource discovery. Security, i.e. authentication, encryption, 
entitlement, etc. is left to be implemented at the application layer, so VLMessaging is not intended for use in hostile 
environments.

In contrast, DCOM, CORBA and other RPC style systems provide models that abstract failure from the programmer providing 
a "simple" interface. However, except possibly in non-scalable toy examples, failure, which is an inherent possibility 
whenever we communicate even with another thread, needs explicit handling. 

VLMessaging makes the resource discovery step explicit and only provides asynchronous and timeout based message sending. 
The goal is to provide a simple to use mental model for building distributed applications, incorporating the idea of 
resource discovery and failure to perform, as fundamental first class concepts rather than abstracting them and
subsequently forcing users to implement workarounds as abstraction leaks are encountered.

To provide robustness, directory entries are responsibility based (so multiple agents can fulfil the same 
responsibility) rather than address based and are replicated to other directories. If an agent goes down then other 
agents providing the same responsibility can be used instead. If a directory goes down then other directories can be 
used for discovery, and any responsibility providers will re-register with other directories when heartbeats fail.

Request / response is built in but other messaging patterns, such as publish / subscribe, guarenteed delivery, 
intentional load-balancing, queuing etc, are left to be implemented at the application level.


## CONCEPTS ##

Msg \
The unit of communication. Contains a subject, body, from address, to address, and other metadata.

Reply \
A msg sent in response to another msg.

Router \
Routes msgs between local connections to other routers for non-local addresses. Handles connection management and 
directory discovery.

Address \
A triplet of machineId, routerId and connectionId that uniquely identifies a connection.

Connection
- msgArrived - call back coroutine that contains a message
- send
  - async, e.g. `conn.send(msg)`
  - semi-synchronous - await reply with timeout, e.g. `reply = await conn.send(msg, 1000)` wait for a reply upto 1 second

Directory
- Entry
  - addr - the address of the connection providing the responsibility
  - service & params - defines the responsibility being provided, e.g. "vol-surface", {"ccy": "USD", "asset-class": "equity", ...}
  - vnets - the virtual-networks the entry is for
  - perms - who can see / use this entry
- VNET - Virtual Network - e.g. "fixed-income-trading-game", "local"
- Hubs
  - Local Hub - the central directory on a machine
  - Network Hub - a well-known directory on the network

AuthService
- Domain
- Perm

Agent / Daemon
- has at least one connection to a router

Routing
- Special addresses
  - LocalHubDirectory - the logical / physical address of the local hub directory on the machine 
  - LocalInterMachineRouter - allows multi-hop routing between machines


## USAGE PATTERNS ##

Act as responsibility provider
1. ask router for the address of a directory
2. send a msg to the address registering self as being available to fulfill specified responsibilities
3. respond to msgs and send periodic heartbeats to the directory to maintain registration

Act as requester
1. ask router for the address of a directory
2. send msg to the address requesting addresses that can fulfill a responsibility
3. send msgs to those addresses and either await replies upto a given timeout or process them asynchronously as they 
   arrive
