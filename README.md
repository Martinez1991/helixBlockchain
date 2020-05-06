Blockchain em Python para IOT


Sobre:

A Blockchain foi desenvolvida para operar junta ao Helix-Sandbox com intuito de garantir a integridade dos dados trafegados no mesmo. 

Requisitos mínimos:

Configuração mínima do servidor: 1 vCPU, 2 GB de RAM e 32GB HDD ou SSD.
Instale qualquer distribuição Linux, de preferência Ubuntu Server 18.04 LTS 

MODO AUTOMÁTICO:

Modo automatiza para baixar e executar a BlockChain:

        sudo git clone https://github.com/Martinez1991/helixBlockchain.git
        cd helixBlockchain
        sudo ./install.sh


Para que funcione de maneira automatica o login e senha do mongodb do broker tem que ser "helix".


MODO MANUAL:

Atualizar o Ubuntu Server:

        sudo apt update
        sudo apt upgrade

Pré-requisitos:

        sudo apt-get install python3
        sudo apt-get install python3-pip
        sudo pip3 install pymongo
        sudo apt install mongodb


Habilitar o Backup:

        sudo apt-get install mysql-server 
        pip3 install mysql-connector-python
        sudo systemctl start mysql

Criar USUÁRIO e DATABASE no MongoDB:

        sudo mysql -e "grant all privileges on *.* to helix@localhost identified by 'pass' with grant option;"
        sudo mysql -u helix –ppass -e “create database helix;”


Para habilitar o Backup, deve-se entrar no arquivo “Backup.py” e alterar as seguintes linhas:


        mydb = mysql.connector.connect(
          host="localhost",
          user="root",
          database="test"
        )

Alterando os valores das variáveis “host”, “user” e “database” de acordo com o seu banco de dados.

Baixar e executar a BlockChain:

        sudo git clone https://github.com/Martinez1991/blockchain.git
        cd blockchain 
        sudo chmod +x Principal.py 
        sudo python3 Principal.py


Caso esteja rodado a blockchain no mesmo servidor do Helix-Sandbox, deve- entrar no arquivo “Principal.py” e alterar as seguintes linhas:
        
        #helix = input("Digite o Ip do Helix: ")
        helix = os.system("wget -qO- ifconfig.co/ip")

Isso fará com que identifique o IP do Broker automaticamente.

