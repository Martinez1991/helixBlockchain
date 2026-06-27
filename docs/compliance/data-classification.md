# Classificação de dados e controles

| Classe | Exemplos | Controles aplicados |
|---|---|---|
| **Secreto** | Chaves privadas Ed25519, token de cluster | Via `*_FILE`/KMS/Vault (#6); nunca em código/log; mTLS no transporte (#1) |
| **Restrito** | IP de clientes (log de auditoria) | Logger `helix.audit`; retenção definida; envio a SIEM |
| **Interno** | Mensagens de consenso, registros (hash) | Assinadas (Ed25519); TLS/mTLS opcional; auth por token |
| **Público** | Altura da cadeia, /health, /metrics | Endpoints de leitura abertos (blocos auto-verificáveis) |

## Trilha de auditoria de acesso

O middleware do servidor emite, no logger **`helix.audit`**, uma entrada por
acesso aos endpoints sensíveis: `method`, `path`, `client` (IP), `authenticated`
e `status`. Encaminhe esse logger ao SIEM (ver notificação SIEM, #12).

## Mapeamento de frameworks (resumo)

| Controle | ISO 27001 (Anexo A) | NIST CSF | SOC 2 (TSC) |
|---|---|---|---|
| Criptografia de segredos | A.8.24 | PR.DS | CC6.1 |
| Integridade de dados (cadeia/Merkle) | A.8.12 | PR.DS-6 | PI1.1 |
| Trilha de auditoria | A.8.15 | DE.AE | CC7.2 |
| Controle de acesso (token/mTLS) | A.5.15/A.8.5 | PR.AC | CC6.1 |
| Backup/recuperação | A.8.13 | PR.IP-4 | A1.2 |
| Gestão de vulnerabilidades (CI) | A.8.8 | ID.RA | CC7.1 |
| Monitoramento (métricas/alertas) | A.8.16 | DE.CM | CC7.2 |

## Roadmap de certificação (esboço)

1. Definir escopo, papéis (controlador/operador) e DPA.
2. Política de retenção/expurgo e classificação aprovadas.
3. Pseudonimização de `entity_id` quando identificar titular (crypto-shredding).
4. SoD e gestão de chaves (KMS/HSM) formalizadas.
5. Evidências de controles (CI de segurança #8, auditoria #17, backups #10) para
   auditoria ISO 27001 / SOC 2 Tipo II.
