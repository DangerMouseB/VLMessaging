# VL-MESSAGING - Very Light Messaging #


## SUMMARY ##

VLMessaging is intended as an easy to use lightweight peer-to-peer messaging system that can route messages between 
agents living in the same thread, and between threads, processes and machines. It provides a failure robust 
responsibility oriented directory service for resource discovery. Security, i.e. authentication, encryption, 
entitlement, etc is left to be implemented at the application layer, so VLMessaging is not intended for use in hostile 
environments.

In contrast DCOM, CORBA and other RPC style systems provide models that abstract failure from the programmer providing 
a "simple" interface. However, except possibly in non-scalable toy examples, failure, which is an inherent possibility 
whenever we communicate even with another thread, needs explicit handling. 

VLMessaging makes the resource discovery step explicit and only provides asynchronous and timeout based message sending. 
The goal is to provide a simple to use mental model for building distributed applications, incorporating the idea of 
resource discovery and failure to perform, as fundamental first class concepts rather than abstracting them and
subsequently forcing users to implement workarounds as abstraction leaks are encountered.

To provide robustness, directory entries are responsibility based (so multiple agents can fulfil the same responsibility) 
and they are replicated to other directories. If an agent goes down then other agents providing the same responsibility 
can be used instead. If a directory goes down then other directories can be used for discovery, and any responsibility 
providers will re-register with other directories when heartbeats fail.

PubSub is supported but other messaging patterns, such as guarenteed delivery, etc, are left to be implemented at the 
application level.


## CONCEPTS ##

Msg \
The unit of communication. Contains a subject, body, from address, to address, and other metadata.

Reply\
A msg sent in response to another msg.

Router

Address

Connection
- msgArrived
- send
  - async
  - semi-synchronous - await reply with timeout

Directory
- Entry
  - Responsibility
  - Scope
- VNET
- Hubs
- Heartbeats

AuthService
- Domain
- Perm

Agent / Daemon
- has at least one connection to a router

Routing
- Special machine level addresses
  - LocalDirectory
  - LocalInterMachineRouter - allows multi-hop routing
- PubSub


## USAGE PATTERNS ##

Act as responsibility provider
1. ask router for the address of a directory
2. send a msg to the address registering self as being available to fulfill specified responsibilities
3. send periodic heartbeats to the address to maintain registration, and respond to Msgs

Act as requester
1. ask router for the address of a directory
2. send msg to the address requesting addresses that can fulfill a responsibility
3. send msgs to those addresses and either await replies upto a given timeout or process them asynchronously as they 
   arrive

