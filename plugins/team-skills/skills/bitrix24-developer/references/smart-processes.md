# Smart Processes Reference

## Known entityTypeIds (Экспресс-Банкрот)

| Smart Process | entityTypeId |
|---------------|-------------|
| Smart-process A (example) | 1094 |
| Smart-process B (example) | 1122 |
| Smart-process C (example) | 1104 |
| Логи встреч/договоров | 1112 |

## Get all smart process types
```
METHOD: crm.type.list
PARAMS: {}
```
Returns `entityTypeId`, `title`, `isCategoriesEnabled`, etc.

## Stage ID format
`DT{entityTypeId}_{categoryId}:{sort}`
- Example: `DT1094_1:10` = entityTypeId 1094, category 1, sort 10
- Category 0 is default (no categories)

## Get stages for smart process
```
METHOD: crm.status.list
PARAMS: {"filter": {"ENTITY_ID": "DYNAMIC_{entityTypeId}_STAGE"}}
```
Or if categories enabled:
```
METHOD: crm.status.list
PARAMS: {"filter": {"ENTITY_ID": "DYNAMIC_{entityTypeId}_STAGE_{categoryId}"}}
```

## Field types in smart processes

| Bitrix type | Description |
|-------------|-------------|
| string | Строка |
| text | Текст |
| integer | Целое число |
| double | Число с плавающей точкой |
| boolean | Флаг Y/N |
| date | Дата |
| datetime | Дата+время |
| enumeration | Список (передавать ID значения) |
| user | Пользователь (передавать USER_ID) |
| crm | Привязка к CRM объекту |
| crm_contact | Контакт |
| crm_deal | Сделка |
| file | Файл |
| iblock_element | Элемент инфоблока |
| money | Деньги (формат: "1000|RUB") |
| url | URL |
| address | Адрес |

## crm.item.list — all params

```json
{
  "entityTypeId": 1094,
  "order": {
    "id": "DESC",
    "updatedTime": "DESC",
    "createdTime": "ASC"
  },
  "filter": {
    "id": 123,
    "stageId": "DT1094_1:1",
    "assignedById": 45,
    "categoryId": 0,
    ">createdTime": "2024-01-01",
    "ufCrm_1_someField": "value"
  },
  "select": [
    "id", "title", "stageId", "assignedById",
    "categoryId", "createdTime", "updatedTime",
    "contactId", "companyId", "opportunity",
    "ufCrm_*"
  ],
  "start": 0
}
```

**Response fields (system)**:
- `id`, `title`, `stageId`, `categoryId`
- `assignedById`, `createdBy`, `updatedBy`
- `createdTime`, `updatedTime`, `movedTime`
- `contactId`, `companyId`
- `opportunity`, `currencyId`
- `isManualOpportunity`
- `opened` (bool)
- `ufCrm_{entityTypeId}_{fieldId}` — custom fields

## Enumeration field values

Get list values:
```
METHOD: crm.item.fields
PARAMS: {"entityTypeId": 1094}
```
Look at `items` array inside enumeration fields — each has `ID` and `VALUE`.
When updating: pass the `ID` (not the VALUE string).

## Relations

```
# Get contacts linked to smart process item
METHOD: crm.item.list
PARAMS: {
  "entityTypeId": 1094,
  "filter": {"id": 123},
  "select": ["contactId", "contactIds"]
}

# Or get via relations
METHOD: crm.item.link.list
PARAMS: {
  "entityTypeId": 1094,
  "entityId": 123
}
```

## Bulk operations pattern (n8n)

For processing many smart process items:
1. `crm.item.list` with pagination (loop on `next`)
2. Collect all IDs into array
3. `SplitInBatches(50)` node
4. Batch `crm.item.update` (max 50 per batch call)
5. Wait 300ms between batches

```
# Batch update example
METHOD: batch
PARAMS: {
  "halt": 0,
  "cmd": {
    "u1": "crm.item.update?entityTypeId=1094&id=101&fields[stageId]=DT1094_1:2",
    "u2": "crm.item.update?entityTypeId=1094&id=102&fields[stageId]=DT1094_1:2"
  }
}
```
