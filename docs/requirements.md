## Requisitos

### Software
- **Python 3.11+**
- Acesso ao **MongoDB** do broker FIWARE Orion a ser monitorado
  - (Opcional) **replica set** se usar coleta por Change Streams
- (Opcional) **Docker / Docker Compose** para a stack de demonstração
- (Opcional) **Kubernetes + Helm** para deploy em HA (`deploy/helm/helix`)
- (Opcional) **PostgreSQL** para persistência em produção (extra `.[postgres]`)
- (Opcional) **Prometheus + Grafana** (métricas/alertas) e coletor **OTLP**
  (tracing, extra `.[otel]`)

### Hardware (por nó validador)
Recomendado: 1 vCPU, 1 GB RAM, 16 GB de disco. Como não há Proof-of-Work, o uso
de CPU é baixo — adequado a cenários de IoT.

### Rede / portas
Cada validador expõe um servidor HTTP (P2P + leitura) e fala com o MongoDB:

```
Porta    Transporte   Uso
8000     TCP          P2P / API do nó (consenso, sync, /chain, /health, /metrics)
27017    TCP          MongoDB do Orion (porta padrão; era 27000 na v1)
```

> Em produção, exponha o P2P sobre **HTTPS/mTLS** e restrinja `/metrics` à rede
> de monitoramento. Ver [security.md](security.md).

Os validadores precisam alcançar uns aos outros na porta P2P, e cada um precisa
alcançar o MongoDB do seu broker.

### Tolerância a falhas
Com **N** validadores, o sistema tolera **f = (N−1)/3** nós bizantinos e exige
quórum **N − f**. Para `f = 1` (tolerar 1 nó malicioso/offline), use **4 nós**.
