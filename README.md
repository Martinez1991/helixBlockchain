## Blockchain em Python para operação no Helix Sandbox Next Generation


## Sobre
Esta blockchain foi desenvolvida para operar em conjunto com Helix Sandbox Next Generation com intuito de garantir a integridade dos dados armazenados nos brokers. Esta não realizar a encriptação dos dados, portanto, não garante confidencialidade. Ela realiza o papel de diversós nós de uma rede blockchain para chegar ao consenso sobre uma informação. Esta "mineração" individual permite à Blockchain funcionar de um modo mais leve e rápido, ideal para o cenário de IoT.

Após sua instalação e execução ela será capaz de verificar se houve alguma alteração na cadeia de brokers federados com o broker principal. Caso algum agente malicioso insira dados diretamente nos brokers federados, esta ação será identificada como ilegítima e a Blockchain o notificará em sua tela de prompt qual foi o dispositivo que sofreu a adulteração.

## Funcionamento
Conforme o diagrama de sua arquitetura, a Blockchain foi projetada para ficar instalada dentro do broker principal, porém, pode ser instalada num equipamento apartado sendo necessário apenas especificar o endereço do broker principal após a instalação.

<img src="https://github.com/Martinez1991/helixBlockchain/blob/master/images/img01_blockchain_diagram.png">

## Requisitos e Instalação

   <a href="docs/requirements.md">Requisitos</a>
   
   <a href="docs/installation.md">Instalação</a>

## Conheça o Helix Sandbox
<a href="https://gethelix.org">Helix</a> for a better world! 
