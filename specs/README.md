# Verificação formal e fuzzing

## TLA+ (`Helix.tla`)

Modelo da **segurança** (safety) do núcleo de consenso IBFT para uma altura:
invariante **Agreement** (dois blocos não podem ambos ser decididos) e
**NoCorrectEquivocation**. A prova reduz-se à interseção de quóruns: com `N`
validadores e `f = (N-1)/3` bizantinos, dois quóruns de tamanho `N-f` sempre se
cruzam num validador correto, que nunca commita dois blocos diferentes.

### Como checar (TLC)

```bash
# Requer Java + tla2tools.jar (https://github.com/tlaplus/tlaplus/releases)
java -cp tla2tools.jar tlc2.TLC -config specs/Helix.cfg specs/Helix.tla
```

TLC explora todos os entrelaçamentos de PREPARE/COMMIT (incluindo o nó bizantino
`v4`) e verifica que `Agreement` e `NoCorrectEquivocation` se mantêm.

> Escopo: o modelo cobre a **segurança de acordo numa altura** — o coração da
> propriedade BFT. Liveness e a troca de rodadas com certificados são exercitadas
> pelos testes e pelo fuzzing (abaixo); estendê-las em TLA+ é trabalho futuro.

## Fuzzing adversarial (`tests/test_fuzz_consensus.py`)

Harness baseado em Hypothesis que entrega sequências aleatórias de mensagens de
consenso (válidas, malformadas e maliciosas) em ordens arbitrárias a um conjunto
de motores e verifica os invariantes de segurança:

- nenhum nó commita **dois blocos diferentes** na mesma altura (acordo);
- todo bloco commitado carrega um **certificado de finalidade válido**;
- mensagens malformadas **nunca derrubam** o motor.

Roda com `pytest tests/test_fuzz_consensus.py`.
