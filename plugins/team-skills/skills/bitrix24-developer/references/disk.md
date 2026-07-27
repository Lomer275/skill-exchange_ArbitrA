# Bitrix24 Disk API Reference

## Rate limits ⚠️
- 500ms between folder reads
- 3000ms between folder writes (to avoid throttling)

## Storage types

| Type | Description |
|------|-------------|
| USER | Personal storage of a user |
| GROUP | Workgroup/project storage |
| SHARED | Shared drive |
| COMPANY | Company drive |

## Get storages

```json
METHOD: disk.storage.getlist
PARAMS: {}
```

## Navigate folder structure

```json
# List root of storage
METHOD: disk.storage.getchildren
PARAMS: {"id": 1}

# List subfolder contents
METHOD: disk.folder.getchildren
PARAMS: {"id": 1234, "filter": {}}

# Get folder info
METHOD: disk.folder.get
PARAMS: {"id": 1234}
```

Response item fields: `ID`, `NAME`, `TYPE` (folder/file), `PARENT_ID`, `SIZE`, `CREATE_TIME`

## Create folder

```json
METHOD: disk.folder.addsubfolder
PARAMS: {
  "id": 1234,
  "data": {"NAME": "Новая папка"}
}
```

## Upload file

```json
METHOD: disk.folder.uploadfile
PARAMS: {
  "id": 1234,
  "data": {"NAME": "document.pdf"},
  "fileContent": ["document.pdf", "BASE64_ENCODED_CONTENT"]
}
```

fileContent format: `["filename", "base64string"]`

## Get file

```json
METHOD: disk.file.get
PARAMS: {"id": 5678}
```

Response includes `DOWNLOAD_URL` for direct download.

## Delete file/folder

```json
METHOD: disk.file.delete
PARAMS: {"id": 5678}

METHOD: disk.folder.delete  
PARAMS: {"id": 1234}
```

## Attach file to CRM entity

```json
METHOD: crm.deal.update
PARAMS: {
  "id": 456,
  "fields": {
    "UF_CRM_FILES": [5678, 5679]
  }
}
```
Or use disk.attachedObject:
```json
METHOD: disk.attachedObject.get
PARAMS: {"id": attachment_id}
```

## Search files

```json
METHOD: disk.folder.getchildren
PARAMS: {
  "id": 1234,
  "filter": {"NAME": "%договор%"}
}
```

## n8n pattern for folder traversal

```javascript
// Recursive folder reader (use SplitInBatches, not recursion)
// 1. Get root children
// 2. For each FOLDER type: queue for processing
// 3. For each FILE type: collect
// 4. Wait 500ms between reads

const children = await this.helpers.httpRequest({
  method: 'POST',
  url: 'https://bitrix.express-bankrot.ru/rest/30351/rzoev7lscjxgq9i6/disk.folder.getchildren',
  body: { id: folderId },
  json: true
});

const folders = children.result.filter(i => i.TYPE === 'folder');
const files = children.result.filter(i => i.TYPE === 'file');
```
