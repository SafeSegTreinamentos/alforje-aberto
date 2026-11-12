# Alforje Aberto

Perfil de Instagram **@alforjeaberto**: destinos pra conhecer de moto, no Brasil e no mundo. Criado e operado por IA.

## Como funciona

1. Os posts ficam na fila em `posts/fila/` (um `.json` por post, publicados em ordem alfabética).
2. Todo dia às 11h07 (Brasília) o GitHub Actions roda `scripts/publish.py`:
   - busca fotos livres no Wikimedia Commons (com crédito ao autor na legenda);
   - monta o carrossel 1080×1350 na identidade do perfil;
   - salva as imagens em `media/<id>/` e publica pela API oficial do Instagram.
3. O post publicado vai pra `posts/publicados/`.

## Configuração

- Segredo do repositório `IG_USER_TOKEN`: token de usuário (Graph API Explorer) com
  `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement`, `business_management`.
- O acesso aos dados do token vence a cada ~90 dias: gere um novo no Graph API Explorer e atualize o segredo.

## Rodar na mão

Aba **Actions → Publicar post do dia → Run workflow**. Marque "Só montar as imagens" pra testar sem publicar.

Fontes: Oswald e Inter (SIL Open Font License).
