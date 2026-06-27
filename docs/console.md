# Console web (`/ui`)

Cada `helix-node` serve um **console read-only** em `GET /ui` — uma SPA estática
(sem build) que consome apenas os endpoints de leitura. Complementa o Grafana
(métricas/alertas): o console é o **explorador da blockchain** e o **board do
cluster**.

## Abas

- **Cluster** — board de todos os nós: status, altura, round, lag, validador/
  follower, validadores/quórum (atualiza a cada 3s, cruza nós via CORS).
- **Blocos** — explorer com drill-down de registros, mudanças de validador e seals.
- **Adulterações** — feed de registros com veredito `TAMPERED`.
- **Validadores** — evolução do conjunto on-chain (gráfico de tamanho por altura,
  timeline de ADD/REMOVE e conjunto ativo atual).
- **Verificar Merkle** — verificação de prova de inclusão **no navegador**
  (espelha `domain/merkle.py`), sem confiar no nó.
- **Ações** — (com token, requer `HELIX_DEBUG_API=true`) submeter registros
  (OK/TAMPERED) e mudar o conjunto de validadores.

## Abrir o console

Rodando o cluster local (ver [installation.md](installation.md)):

<div id="connect">
  <input id="nodeUrl" value="http://localhost:8001" style="min-width:280px">
  <button onclick="openUi()">Abrir console do nó ↗</button>
  <button onclick="embedUi()">Embutir abaixo</button>
  <p id="hint" style="font-size:13px;opacity:.8"></p>
  <iframe id="frame" style="display:none;width:100%;height:640px;border:1px solid #ccc;border-radius:8px"></iframe>
</div>
<script>
function base(){return document.getElementById('nodeUrl').value.replace(/\/$/,'');}
function openUi(){window.open(base()+'/ui','_blank');}
function embedUi(){
  const f=document.getElementById('frame'), h=document.getElementById('hint');
  if(location.protocol==='https:' && base().startsWith('http://')){
    h.textContent='⚠️ Esta página é HTTPS e não pode embutir um nó http:// (mixed content). '
      +'Use "Abrir console do nó" (abre numa aba), sirva os docs localmente (mkdocs serve) '
      +'ou exponha o nó via HTTPS.';
    return;
  }
  f.src=base()+'/ui'; f.style.display='block'; h.textContent='';
}
</script>

> O "Abrir console do nó" funciona mesmo a partir do site HTTPS (é navegação, não
> *embed*). Embutir um nó `http://localhost` numa página HTTPS é bloqueado pelo
> navegador (mixed content) — sirva os docs localmente (`mkdocs serve`) ou exponha
> o nó por HTTPS para embutir.
