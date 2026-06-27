# LGPD — Mapeamento de dados e responsabilidades

> Documento de apoio à conformidade. Não substitui parecer jurídico. Ajuste aos
> papéis (controlador/operador) e bases legais do seu contexto.

## Natureza da solução

O Helix Blockchain garante **integridade** (não confidencialidade) de dados de
contexto IoT do FIWARE Orion. A cadeia **não armazena o valor bruto** dos
atributos: guarda o **hash do valor** (`value_hash`), o que minimiza a exposição
de dados (princípio da **minimização**, art. 6º III).

## Dados tratados (inventário)

| Dado | Onde | Pessoal? | Observação |
|---|---|---|---|
| `entity_id` | bloco (registro) | **Potencialmente** | Pode identificar dispositivo/pessoa conforme a modelagem do broker |
| `attribute` | bloco | Não | Nome do atributo (ex.: `temperature`) |
| `value_hash` | bloco | Não (hash) | Hash do valor observado; não reversível |
| `source_broker` | bloco | Não | Host do broker federado |
| `observer` (pubkey) | bloco | Não | Identidade do validador que assinou |
| `observed_at` | bloco | Não | Timestamp |
| IP de origem | log de auditoria | **Sim** | Endereço de rede do cliente P2P/admin |

> Se `entity_id` puder identificar um titular, trate-o como **dado pessoal** e
> ative a **pseudonimização** (`HELIX_PSEUDONYMIZE_ENTITIES=true` +
> `HELIX_COMMIT_KEY_*`): grava `pid:HMAC(chave, entity_id)`. O `value_hash`
> também passa a ser um **commitment com chave** (HMAC), evitando força-bruta de
> valores de baixa entropia. Ver [../security.md](../security.md#confidencialidade).

## Bases legais (exemplos a confirmar)

- Operação do serviço/segurança da informação: **legítimo interesse** (art. 7º IX)
  ou **execução de contrato** (art. 7º V), conforme o caso de uso.
- Logs de auditoria de acesso: **cumprimento de obrigação legal/regulatória** e
  segurança (art. 7º II/IX).

## Direitos do titular

- A cadeia é **append-only e imutável** por design — a "eliminação" de um registro
  específico conflita com a imutabilidade. Mitigações:
  - não registrar dado pessoal diretamente (somente `value_hash` + id
    pseudonimizado);
  - para o direito de eliminação, manter a **chave de pseudonimização/commit**
    (`HELIX_COMMIT_KEY_*`) separada e, ao atender a solicitação, **destruir a
    chave** (tornando id e `value_hash` irreversíveis — *crypto-shredding*).
- Solicitações de acesso/correção referentes ao **dado de origem** devem ser
  atendidas no FIWARE Orion (sistema de origem), não na cadeia de integridade.

## Retenção

Ver [../operations.md](../operations.md). Backups têm retenção configurável; a
cadeia é append-only (considere *checkpointing*/arquivamento para horizontes
longos). Logs de auditoria devem ter retenção definida por política (ex.: 1 ano).

## Operador × Controlador

Tipicamente o Helix atua como **operador** (processa dados do broker em nome do
controlador). Formalize via contrato/DPA e registre as instruções de tratamento.
