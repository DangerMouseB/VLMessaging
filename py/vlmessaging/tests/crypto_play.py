from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes


# https://leducphong.medium.com/best-crypto-libraries-for-python-developers-43cd3d93d49c

# https://github.com/pyca/cryptography - cryptography
# https://cryptography.io/en/3.3.1/index.html
# https://nacl.cr.yp.to/

# https://www.pycryptodome.org/ - pycryptodome and pycryptodomex

# https://www.nist.gov/news-events/news/2022/07/nist-announces-first-four-quantum-resistant-cryptographic-algorithms

# https://www.reddit.com/r/AskNetsec/comments/15i0nzp/aes256_is_quantum_resistant_for_now/
# https://crypto.stackexchange.com/questions/113154/how-is-aes-128-still-considered-to-be-quantum-resistant
# https://en.wikipedia.org/wiki/Grover%27s_algorithm
# https://eprint.iacr.org/2022/683

# https://medium.com/techanic/the-math-in-public-key-cryptography-in-simple-words-with-examples-e3a18cb4fa85

# RSA in Python
# https://stackoverflow.com/questions/8539441/private-public-encryption-in-python-with-standard-library
# https://www.askpython.com/python/examples/rsa-algorithm-in-python
# https://www.reubenbinns.com/blog/self-sufficient-programming-rsa-cryptosystem-with-plain-python/


# https://blog.cryptographyengineering.com/useful-cryptography-resources/
# https://leducphong.medium.com/zero-knowledge-proof-learning-resources-a-learning-path-5f7a1e4a90aa

def genKeys():
    auth_agent_pvt = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    with open('/Users/david/arwen/VLMessaging/py/vlmessaging/tests/keys/auth_agent_pvt.pem', 'wb') as f:
        f.write(
            auth_agent_pvt.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.BestAvailableEncryption(b'your_very_strong_password_here')
                # encryption_algorithm = serialization.NoEncryption()
            )
        )
    with open('/Users/david/arwen/VLMessaging/py/vlmessaging/tests/keys/auth_agent_pub.pem', 'wb') as f:
        f.write(
            auth_agent_pvt.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )

    dm_pvt = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    with open('/Users/david/arwen/VLMessaging/py/vlmessaging/tests/keys/dm_pvt.pem', 'wb') as f:
        f.write(
            dm_pvt.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.BestAvailableEncryption(b'your_very_strong_password_here')
                # encryption_algorithm=serialization.NoEncryption()
            )
        )
    with open('/Users/david/arwen/VLMessaging/py/vlmessaging/tests/keys/dm_pub.pem', 'wb') as f:
        f.write(
            dm_pvt.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )

    penfold_pvt = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    with open('/Users/david/arwen/VLMessaging/py/vlmessaging/tests/keys/penfold_pvt.pem', 'wb') as f:
        f.write(
            penfold_pvt.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.BestAvailableEncryption(b'your_very_strong_password_here')
            )
        )
    with open('/Users/david/arwen/VLMessaging/py/vlmessaging/tests/keys/penfold_pub.pem', 'wb') as f:
        f.write(
            penfold_pvt.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )

# genKeys()


# dm loads the auth agent's public key and own keys
with open('/Users/david/arwen/VLMessaging/py/vlmessaging/tests/keys/auth_agent_pub.pem', 'rb') as f:
    auth_agent_pub = serialization.load_pem_public_key(f.read())

with open('/Users/david/arwen/VLMessaging/py/vlmessaging/tests/keys/dm_pvt.pem', 'rb') as f:
    dm_pvt = serialization.load_pem_private_key(
        f.read(),
        password=b'your_very_strong_password_here',
    )
    dm_pub = dm_pvt.public_key()

# dm chooses key for dm <--> auth agent
dm_auth_agent_session_key = Fernet.generate_key()


# dm encrypts the key
encrypted_msg = auth_agent_pub.encrypt(
    dm_auth_agent_session_key,
    padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None
    )
)

# dm signs the encrypted msg
signature = dm_pvt.sign(
    encrypted_msg,
    padding.PSS(
        mgf=padding.MGF1(hashes.SHA256()),
        salt_length=padding.PSS.MAX_LENGTH
    ),
    hashes.SHA256()
)


# auth agent load's its private key
with open('/Users/david/arwen/VLMessaging/py/vlmessaging/tests/keys/auth_agent_pvt.pem', 'rb') as f:
    auth_agent_pvt = serialization.load_pem_private_key(
        f.read(),
        password=b'your_very_strong_password_here',
    )

#  and the agent's public keys
with open('/Users/david/arwen/VLMessaging/py/vlmessaging/tests/keys/dm_pub.pem', 'rb') as f:
    dm_pub = private_key = serialization.load_pem_public_key(f.read())

with open('/Users/david/arwen/VLMessaging/py/vlmessaging/tests/keys/penfold_pub.pem', 'rb') as f:
    penfold_pub = f.read()


# auth agent verifies the message is from dm
dm_pub.verify(
    signature,
    encrypted_msg,
    padding.PSS(
        mgf=padding.MGF1(hashes.SHA256()),
        salt_length=padding.PSS.MAX_LENGTH
    ),
   hashes.SHA256()
)

# unencrypts the message
key_from_dm = auth_agent_pvt.decrypt(
    encrypted_msg,
    padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()),
        algorithm=hashes.SHA256(),
        label=None
    )
)


f = Fernet(key_from_dm)
token = f.encrypt(b"my deep dark secret")
print(token)
print(f.decrypt(token))


