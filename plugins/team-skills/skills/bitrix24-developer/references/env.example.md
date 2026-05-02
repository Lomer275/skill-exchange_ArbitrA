# Bitrix24 Environment — пример

Скопируй этот файл в свой проект как `BITRIX_ENV.md` и заполни своими значениями.
**Никогда не коммить заполненный файл с реальным WEBHOOK_TOKEN.** Добавь его в `.gitignore`.

## Portal

```
Portal:        bitrix.example.com               # → твой Bitrix24 домен
Webhook user:  <USER_ID>                        # ID пользователя, от чьего имени работает webhook
Webhook token: <WEBHOOK_TOKEN>                  # секретный токен (Битрикс24 → Разработчикам → Входящий вебхук)
Webhook base:  https://<PORTAL>/rest/<USER_ID>/<WEBHOOK_TOKEN>/
```

## Воронки (CATEGORY_ID)

Узнай через `crm.category.list`:

```
| Funnel name        | CATEGORY_ID |
|--------------------|-------------|
| <Main pipeline>    | <ID>        |
| <Other pipeline>   | <ID>        |
```

## Smart Processes (entityTypeId)

Узнай через `crm.type.list`:

```
| Smart Process      | entityTypeId | Stage prefix      |
|--------------------|--------------|-------------------|
| <Process A>        | <typeId>     | DT<typeId>_<cat>: |
```

## Custom Fields (UF_CRM_*)

Узнай через `crm.deal.userfield.list` (для сделок) или `crm.item.fields` с `entityTypeId` (для смарт-процессов).

## n8n bridge (если используешь)

```
n8n base URL:   https://n8n.example.com
Bridge workflow ID: <N8N_BRIDGE_WORKFLOW_ID>
```
