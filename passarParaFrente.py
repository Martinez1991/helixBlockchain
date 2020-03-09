from Block import *
from Funcoes import *
import os

def main():

    genesis = Block(0, "", ts, "Genesis block", calculateHash(0, "", ts, "Genesis block", 2, 0), 2, 0)
    bc = Blockchain(genesis)
    helix = os.system("wget -qO- ifconfig.co/ip")
    while True:

        helix1Ent = conectaEntidade(helix, 27017)
        helix1Csub = conectaCsubs(helix, 27017)

        helix2 = findFederado(helix1Csub)

        fed = Federa(helix2,helix1Csub, helix1Ent,bc)

        if fed != []:

            for linha in fed:
                Federa(linha, helix1Csub, helix1Ent, bc)


        ''' 
        if helix2 != []:

            for linha in helix2:

                helix2Ent = conectaEntidade(linha, 27017)

                dadosEntHelix2 = getDadosProximoHelix(helix2Ent)

                dadosFederado = dadosFederados(helix1Csub, helix1Ent)

                validaFederado = validaFederados(dadosFederado, dadosEntHelix2)

                monitoraFederado = monitora(validaFederado)

                atualizar(monitoraFederado, bc)

                helix2Csub = conectaCsubs(helix, 27017)
                helixx = findFederado(helix2Csub)

        else:
            pass
        '''

        lista1 = monitora(gravaDB(helix1Ent))

        atualizar(lista1, bc)


        print("\n\n\n")
        print('-' * 60)
        print(f'                     {"Blockchain  Helix"}')
        print('-' * 60)
        print("\n\n")
        bc.print_blocos()

        time.sleep(1)

if __name__ == '__main__':
    main()





