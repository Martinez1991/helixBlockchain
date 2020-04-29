from pymongo import MongoClient
import threading
import csv
from pprint import pprint
import time


# função conectaEntidade() conecta e trás  todos os dados do Orion e salva uma Lista
def conectaEntidade(ip, porta):
    client = MongoClient(ip, porta)
    mydb = client["orion"]
    mycol = mydb["entities"]
    return mycol


# função conectaCsubs() conecta e trás  todos os dados do Orion e salva uma Lista
def conectaCsubs(ip, porta):
    client = MongoClient(ip, porta)
    mydb = client["orion"]
    mycol = mydb["csubs"]
    return mycol



# função gravaDB() grava todos os dados do MongoDB em uma Lista
def gravaDB(entities):
    cursor = entities.find()
    lista = []
    for linha in cursor:
        lista.append(linha)
    return lista


# função monitora() monitora para ver se houve atualização de qualquer dado do MongoDB.
def monitora(dados, lastreslt=[]):
    myresult = dados
    prova = []
    for x in myresult:
        if x not in lastreslt:
            lastreslt.append(x)
            prova.append(x)
    return prova


# função trans1() trás o Id e o valor do divice "csubs" do MongoDB, cujo os dados são dos IoTs FEDERADOS.
def dadosFederados(csubs,entities):
    cursor2 = csubs.distinct("entities.id")
    lista = []
    for document in cursor2:
        a = entities.find_one({"_id.id": document}, {"attrs.temperature.value"})
        lista.append(a)
    return lista


# função getDadosProximoHelix() trás todos os dados do "entities" do MongoDB do helix a ser validado
def getDadosProximoHelix(entidades):
    lista1 = []
    cursor1 = entidades.distinct("_id.id")
    for lin in cursor1:
        a = entidades.find_one({"_id.id": lin}, {"attrs.temperature.value"})
        lista1.append(a)
    return lista1



# função validaFederados() valida se o dado do 1ª banco de dados está igual ao do 2ª
def validaFederados(csubs,entidade):
    helix1 = csubs
    helix2 = entidade
    listaTest = []
    for x in helix1:
        if x in helix2:
            listaTest.append(x)
        else:
            a = str(x)
            a = a.split("'")[5]
            print('~' * 40)
            print(f'    {"Divice " + a + " Foi adulterado"}')
            print('~' * 40)
    return listaTest



# função atualiza() valida se o dado será o não grava na Blockchain
def atualizar(dados, chain):
    lista = dados
    if lista != []:
        for i in range(0, len(lista)):
            test = lista[i]
            chain.generateNextBlock(str(test))




# função findFederado() procura os Ip dos outros Brokers Federados
def findFederado(csubs):
    cursor2 = csubs.distinct("reference")
    lista = []
    for document in cursor2:
        srt = str(document)
        srt = srt.split("/")[2]
        srt = srt.split(":")[0]
        lista.append(srt)
    return lista


def Federa(ip, helix1Csub, helix1Ent, bc):

    if ip != []:

        for linha in ip:

            helix2Ent = conectaEntidade(linha, 27017)

            helix2Csub = conectaCsubs(linha, 27017)

            dadosEntHelix2 = getDadosProximoHelix(helix2Ent)

            dadosFederado = dadosFederados(helix1Csub, helix1Ent)

            validaFederado = validaFederados(dadosFederado, dadosEntHelix2)

            monitoraFederado = monitora(validaFederado)

            atualizar(monitoraFederado, bc)

            proc = procuraId(helix1Ent, helix2Csub)
            print(proc)

    return proc


# função findFederado() procura os Ip dos outros Brokers Federados e valida se está nno primeiro broker
def procuraId(ent, csub):
    cursor2 = ent.distinct("_id.id")
    lista = []
    for document in cursor2:
        a = csub.find_one({"entities.id": document}, {"reference"})
        aa = csub.distinct("entities.id")
        if document in aa:
            srt = str(a)
            srt2 = srt.split("'http://")[1::]
            srt2 = str(srt2)
            srt3 = srt2.split(":1026/v2/op/notify")[0]
            srt3 = str(srt3)
            srt4 = srt3.replace('"',"")
            srt5 = srt4.replace('[',"")
            print(srt5)
            lista.append(srt5)
    return lista