address \
connection \
router 

authentication agent - authentication and trust
- has users 
- keeps symmetry key per user.router pair
- keeps log lived tokens?

virtual network 
- a group of services / directories
- directory entry belongs to a vnet

keep separate signing keys and exchanging keys


SSO is basically about using the sign on to an authentication agent to do more

private keys can be encrypted with an authentication agent token and a local password

2 factoring auth can be used to allow the token to be shared with a client

user has two RSA keys - one for the first step of logging on and the second (post 2 factor verification) that is 
decrypted by the agents token for subsequent communication

does the connection or the router handle the end-to-end encryption?
