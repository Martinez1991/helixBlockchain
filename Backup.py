import mysql.connector
from mysql.connector import errorcode
from Block import *
from Funcoes import *

mydb = mysql.connector.connect(
  host="localhost",
  user="root",
  database="test"
)


cursor = mydb.cursor(buffered=True)
mycursor = mydb.cursor()


mycursor.execute("CREATE TABLE Blockchain ( id INT(10) UNSIGNED PRIMARY KEY AUTO_INCREMENT, ind INT(10) NOT NULL, HashAnterior VARCHAR(100), Times float(50) NOT NULL, dados VARCHAR(5000) NOT NULL, hash VARCHAR(100) NOT NULL, Dificuldade INT(10) NOT NULL, Nonce float(50) NOT NULL)")


