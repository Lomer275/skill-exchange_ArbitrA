# Smart Processes Reference

All writes must follow the [Write policy](../SKILL.md#write-policy-mandatory).

## Known entityTypeIds (Express-Bankrot)

| Smart Process | entityTypeId |
|---------------|-------------|
| KadArbitr | 1094 |
| EFRSB/Fedresurs | 1122 |
| Employee conversion | 1104 |
| Meeting/contract logs | 1112 |

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
| string | String |
| text | Text |
| integer | Integer |
| double | Floating-point number |
| boolean | Y/N flag |
| date | Date |
| datetime | Date+time |
| enumeration | List (pass the value ID) |
| user | User (pass USER_ID) |
| crm | Link to a CRM object |
| crm_contact | Contact |
| crm_deal | Deal |
| file | File |
| iblock_element | Infoblock element |
| money | Money (format: "1000|RUB") |
| url | URL |
| address | Address |

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

1. Read all candidates with `crm.item.list`, following every `next` page;
   select `id`, `title`, and the current `stageId`. No writes yet.
2. Show every item ID, entityTypeId, method `crm.item.update`, and
   `stageId: <current value> → DT1094_1:2` in the full proposed plan.
3. Wait for the human's explicit “yes” to that list; use the project sandbox
   first if available and follow the production write route in the Write policy.
4. Only then send approved IDs through `SplitInBatches(50)` to write batches
   with `halt: 1`; stop the whole workflow on any `result_error`.
5. Wait 300ms between batches. Read back results; a revised plan after a failure
   requires a new confirmation before retrying.

```
# Write phase only: IDs 101 and 102 must be in the confirmed plan
METHOD: batch
PARAMS: {
  "halt": 1,
  "cmd": {
    "u1": "crm.item.update?entityTypeId=1094&id=101&fields[stageId]=DT1094_1:2",
    "u2": "crm.item.update?entityTypeId=1094&id=102&fields[stageId]=DT1094_1:2"
  }
}
```
