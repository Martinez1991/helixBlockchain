import mysql.connector
from mysql.connector import errorcode
from Block import *
from Funcoes import *



try:
	mydb = mysql.connector.connect(
  	  host="localhost",
          user="helix",
          password="pass",
	  database="helix"
        )


	print("Database connection made!")

except mysql.connector.Error as error:

	if error.errno == errorcode.ER_BAD_DB_ERROR:

		print("Database doesn't exist")

	elif error.errno == errorcode.ER_ACCESS_DENIED_ERROR:

		print("User name or password is wrong")

	else:

		print(error)

else:

	cursor = mydb.cursor(buffered=True)
	mycursor = mydb.cursor()


	mycursor.execute("CREATE TABLE Blockchain ( id INT(10) UNSIGNED PRIMARY KEY AUTO_INCREMENT, ind INT(10) NOT NULL, HashAnterior VARCHAR(100), Times float(50) NOT NULL, dados VARCHAR(5000) NOT NULL, hash VARCHAR(100) NOT NULL, Dificuldade INT(10) NOT NULL, Nonce float(50) NOT NULL)")


