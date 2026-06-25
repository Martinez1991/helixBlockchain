import hashlib
import time
import binascii

class Block:
    def __init__(self, index, previousHash, timestamp, data, hash, difficulty, nonce):
        self.index = index
        self.previousHash = previousHash
        self.timestamp = timestamp
        self.data = data
        self.hash = hash
        self.difficulty = difficulty
        self.nonce = nonce

    def print_bloco(self):
        print("Índice:", self.index)
        print("Hash anterior:", self.previousHash)
        print("Timestamp:", self.timestamp)
        print("Dados:", self.data)
        print("Hash:", self.hash)
        print("Dificuldade:", self.difficulty)
        print("Nonce:", self.nonce)

class Blockchain:
    def __init__(self, genesisBlock):
        self.__chain = []
        self.__chain.append(genesisBlock)
        self.DIFFICULTY_ADJUSTMENT = 50
        self.BLOCK_INTERVAL = 120

    def getLastestBlock(self):
        return self.__chain[len(self.__chain) - 1]

    def generateNextBlock(self, data):
        previousBlock = self.getLastestBlock()
        nextIndex = previousBlock.index + 1
        nextTimestamp = int(round(time.time() * 1000))
        nextPreviousHash = previousBlock.hash
        nextdifficulty = self.getDifficulty()
        nonce = str(0)
        newBlock = Block(nextIndex, nextPreviousHash, nextTimestamp, data,
                         calculateHash(nextIndex, nextPreviousHash, nextTimestamp, data, nextdifficulty, nonce),
                         nextdifficulty, nonce)
        if self.validatingBlock(newBlock) == True:
            self.__chain.append(self.findBlock(nextIndex, nextPreviousHash, nextTimestamp, data, nextdifficulty))


    def validatingBlock(self, newBlock):
        previousBlock = self.getLastestBlock()
        if previousBlock.index + 1 != newBlock.index:
            return False
        elif previousBlock.hash != newBlock.previousHash:
            return False
        return True

    def hashMatchesDifficulty(self, hash, difficulty):
        hashBinary = binascii.unhexlify(hash)
        requiredPrefix = '0'*int(difficulty)
        requiredPrefix = binascii.a2b_hex(requiredPrefix.strip())
        return hashBinary.startswith(requiredPrefix)


    def findBlock(self, index, previousHash, timestamp, data, difficulty):
        nonce = 0
        while True:
            hash = calculateHash(index, previousHash, timestamp, data, difficulty, nonce)
            if self.hashMatchesDifficulty(hash, self.getDifficulty()):
                block = Block(index, previousHash, timestamp, data, hash, difficulty, nonce)
                return block
            nonce = nonce + 1

    def getDifficulty(self):
        latestBlock = self .getLastestBlock()
        if latestBlock.index % self.DIFFICULTY_ADJUSTMENT == 0 and latestBlock.index != 0:
            return self.getAdjustedDifficulty()
        else:
            return latestBlock.difficulty


    def getAdjustedDifficulty(self):
        latestBlock = self.getLastestBlock()
        prevAdjustmentBlock = self.__chain[len(self.__chain) - self.DIFFICULTY_ADJUSTMENT]
        timeExpected = self.BLOCK_INTERVAL * self.DIFFICULTY_ADJUSTMENT
        timeTaken = latestBlock.timestamp - prevAdjustmentBlock.timestamp
        if timeTaken < timeExpected * 2:
            return prevAdjustmentBlock.difficulty + 1
        elif timeTaken > timeExpected * 2:
            return prevAdjustmentBlock.difficulty - 1
        else:
            return  prevAdjustmentBlock.difficulty

    def bancoBlockChain(self, mycursor, mydb, lastreslt=[]):
        for block in self.__chain:
            if block not in lastreslt:
                sql = "INSERT INTO Blockchain (ind, HashAnterior, Times, dados, hash, Dificuldade, Nonce) VALUES (%s, %s, %s, %s, %s, %s, %s)"
                var = (
                block.index, block.previousHash, block.timestamp, block.data, block.hash, block.difficulty, block.nonce)
                mycursor.execute(sql, var)
                mydb.commit()
                lastreslt.append(block)



    def print_blocos(self):
        for bloco in self.__chain:
            bloco.print_bloco()
            print()


def calculateHash(index, previousHash, timestamp, data, difficulty, nonce):
    return hashlib.sha256((str(index) + previousHash + str(timestamp) + data + str(difficulty) + str(nonce)).encode('utf-8')).hexdigest()

ts = int(round(time.time() * 1000))


