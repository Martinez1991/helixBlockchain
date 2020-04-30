#!/bin/bash

#Atualizar o Ubuntu Server:

sudo apt update
wait
sudo apt upgrade
wait

#Pré-requisitos:

sudo apt-get install python3
wait
sudo apt-get install python3-pip
wait
sudo pip3 install pymongo
wait
sudo apt install mongodb
wait

#Habilitar o Backup:

sudo apt-get install mysql-server
wait
pip3 install mysql-connector-python
wait

sudo systemctl start mysql
wait

#Cria database
#sudo mysql -e “grant all privileges on *.* to helix@localhost identified by 'pass' with grant option;”
#sudo mysql -u helix –ppass -e “create database helix;”

SQL="create database helix; use mysql; grant all privileges on *.* to helix@localhost identified by 'pass' with grant option;"
sudo mysql -u helix -ppass -e "$SQL"


sleep 10

#Instala e executa
sudo chmod +x Principal.py
sudo python3 Principal.py

