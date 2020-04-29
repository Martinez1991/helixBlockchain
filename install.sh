#!/bin/bash

#Atualizar o Ubuntu Server:

sudo apt update
wait
sudo apt upgrade
wait

#Pré-requisitos:

sudo apt-get install python3 -y
wait
sudo apt-get install python3-pip -y
wait
sudo pip3 install pymongo -y
wait
sudo apt install mongodb -y
wait

#Habilitar o Backup:

sudo apt-get install mysql-server –y
wait
pip3 install mysql-connector-python -y
wait

sudo systemctl start mysql -y
wait

#Cria database
sudo myslq -e grant all privileges on *.* to helix@localhost identified by 'pass' with grant option;
sudo mysql -u helix –ppass -e “create database helix;”
sleep 10

#Instala e executa
sudo chmod +x Principal.py
sudo python3 Principal.py

