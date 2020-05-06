from Block import *
from Funcoes import *
from Backup import *
import os
import subprocess

def main():

    genesis = Block(0, " ", ts, "Genesis block", calculateHash(0, "", ts, "Genesis block", 2, 0), 2, 0)
    bc = Blockchain(genesis)
    #helix = input("Digite o Ip do Helix: ")
    helix = subprocess.getoutput("wget -qO- ifconfig.co/ip")
    print (helix)
    while True:

        helix1Ent = conectaEntidade(helix,27000)
        try:
            helix1Csub = conectaCsubs(helix,27000)
            helix2 = findFederado(helix1Csub)
            fed = Federa(helix2,helix1Csub, helix1Ent,bc)
            if fed != []:
            	for linha in fed:
                    print(linha)
                    Federa(linha, helix1Csub, helix1Ent, bc)

        except Exception:
             pass # or you could use 'continue'..

        lista1 = monitora(gravaDB(helix1Ent))

        atualizar(lista1, bc)

        print("\n\n\n")
        print('-' * 60)
        print(f'                     {"Blockchain  Helix"}')
        print('-' * 60)
        print("\n\n")
        bc.print_blocos()

        bc.bancoBlockChain(mycursor, mydb)

        time.sleep(1)

if __name__ == '__main__':
    main()





