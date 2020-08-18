## Instalação
É recomendado que a instalação seja feita dentro do servidor principal do Helix, caso esta seja instalada num outro servidor é necessário utilizar o método manual de instalação para definir o IP onde o Helix se encontra. 

Vale ressaltar que para que o modo automático funcione corretamente o login e senha pré-configurados do MongoDB do broker devem permanecer como "helix" para o usuário e  "H3l1xNG" para a senha. Caso tal configuração seja alterada, deve-se alterar no código da blockchain também.

## Modo automático:
Modo automatizado para baixar e executar a Blockchain:

        sudo git clone https://github.com/Martinez1991/helixBlockchain.git
        cd helixBlockchain
        sudo ./install.sh

## Modo manual:
Primeiramente atualize seu Ubuntu Server:

        sudo apt update
        sudo apt upgrade

Realize a instalação dos pré-requisitos:

        sudo apt-get install python3
        sudo apt-get install python3-pip
        sudo pip3 install pymongo
        sudo apt install mongodb

Habilite o Backup:

        sudo apt-get install mysql-server 
        pip3 install mysql-connector-python
        sudo systemctl start mysql

Crie um USUÁRIO e um DATABASE no MongoDB:

        sudo mysql -e "grant all privileges on *.* to helix@localhost identified by 'pass' with grant option;"
        sudo mysql -u helix –ppass -e “create database helix;”

Para habilitar o Backup, deve-se entrar no arquivo “Backup.py” e alterar as seguintes linhas:

        mydb = mysql.connector.connect(
          host="localhost",
          user="root",
          database="test"
        )

Atenção: Altere os valores das variáveis “host”, “user” e “database” de acordo com o seu banco de dados.

Baixe e execute a Blockchain:

        sudo git clone https://github.com/Martinez1991/blockchain.git
        cd blockchain 
        sudo chmod +x Principal.py 
        sudo python3 Principal.py

Caso esteja rodando a blockchain num servidor apartado do Helix-SandboxNG, deve-se entrar no arquivo “Principal.py” e alterar as linhas abaixo para definir o IP do Helix
        
        #helix = input("<HELIX_IP>")
        helix = os.system("wget -qO- ifconfig.co/ip")
