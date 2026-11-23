# Команды gh для issues и Projects

Использовать только для выбранного действия после проверки разрешений в SKILL.md.
Нужны `gh`, Bash и `jq`. Перед записью проверить поддержку флагов локальным
`gh ... --help`. Не включать вывод токенов, `set -x` и чтение файлов секретов.

## Параметры и чтение

Задать `REPO=owner/repository`, `OWNER=владелец_доски`, `PROJECT=номер_доски`,
`N=номер_issue` из подтверждённого контекста. Не выполнять примеры с буквальными
заполнителями. В shell включить `set -euo pipefail`. Issues с одинаковым номером в разных репозиториях —
разные объекты; всегда указывать `--repo`.

```bash
gh issue view "$N" --repo "$REPO" --json number,url,title,body,state,stateReason,assignees,labels
gh issue view "$N" --repo "$REPO" --comments
gh project view "$PROJECT" --owner "$OWNER" --format json
gh project field-list "$PROJECT" --owner "$OWNER" --limit 100 --format json
```

Поиск перед созданием: `gh issue list --repo "$REPO" --state all --search "$QUERY"`.
Поиск по человеку: `gh issue list --repo "$REPO" --assignee "$LOGIN" --state open`.
Ограниченный список не считать полным: выбрать достаточный `--limit`/пагинацию,
уточнить поиск по смысловым словам и номеру спецификации. Для списка задач не
выводить лишние описания и переписку в общий отчёт.

## Создание и комментарий

Сначала подготовить и прочитать файл `BODY_FILE`; определить `TITLE`, `ASSIGNEE`
(ровно один проверенный login), `LABEL` (согласованная существующая метка проекта).
Не ставить эту метку фиктивной спецификации в учебной/служебной задаче.

```bash
[[ "$ASSIGNEE" =~ ^[[:alnum:]][[:alnum:]-]*$ ]] || { echo 'Нужен один login' >&2; exit 1; }
test -s "$BODY_FILE" && test -n "$TITLE"
ISSUE_URL=$(gh issue create --repo "$REPO" --title "$TITLE" \
  --assignee "$ASSIGNEE" --label "$LABEL" --body-file "$BODY_FILE")
N=${ISSUE_URL##*/}
gh issue view "$N" --repo "$REPO" --json assignees |
  jq -e --arg login "$ASSIGNEE" '.assignees | length == 1 and .[0].login == $login'
```

У учебной/служебной issue убрать `--label "$LABEL"`. Если назначение не
подтвердилось, перечитать созданную issue и разобраться, не создавать вторую.
Редактирование описания: сначала прочитать текущий body, сохранить чужие правки,
затем `gh issue edit "$N" --repo "$REPO" --body-file "$BODY_FILE"`.
Комментарий из просмотренного файла: `gh issue comment "$N" --repo "$REPO" --body-file "$REPORT_FILE"`.
Проверка отправки — перечитать комментарии и найти фактический результат/ID.

## Карточка и статус

Выполнять заново перед изменением или после переоткрытия/восстановления карточки.
Не путать номер issue с ID карточки; поиск по полному URL исключает совпадение
номеров в разных репозиториях. Не считать карточку отсутствующей при неполной выборке.

```bash
ISSUE_URL=$(gh issue view "$N" --repo "$REPO" --json url --jq .url)
PROJECT_ID=$(gh project view "$PROJECT" --owner "$OWNER" --format json --jq .id)
FIELDS_JSON=$(gh project field-list "$PROJECT" --owner "$OWNER" --limit 100 --format json)
STATUS_FIELD_ID=$(jq -er '[.fields[] | select(.name == "Status")] |
  if length == 1 then .[0].id else error("Нет единственного Status") end' <<< "$FIELDS_JSON")
ITEMS_JSON=$(gh project item-list "$PROJECT" --owner "$OWNER" --limit 1000 --format json)
jq -e '(.items | length) == .totalCount' <<< "$ITEMS_JSON" >/dev/null || {
  echo 'Список неполный: увеличьте limit или используйте пагинацию' >&2; exit 1;
}
ITEM_ID=$(jq -er --arg url "$ISSUE_URL" '[.items[] | select(.content.url == $url)] |
  if length == 1 then .[0].id else error("Нет однозначной карточки") end' <<< "$ITEMS_JSON")
jq --arg id "$ITEM_ID" '.items[] | select(.id == $id) | {id,status,url:.content.url}' <<< "$ITEMS_JSON"
```

После разрешённой постановки/сдачи/возврата задать `TARGET_STATUS` точным именем.
Задать также `DONE_STATUS` именем конечного статуса из профиля. Следующий блок пишет в GitHub. Если статус уже нужный — пропустить запись.

```bash
OPTION_ID=$(jq -er --arg name "$TARGET_STATUS" '[.fields[] | select(.name == "Status") |
  .options[] | select(.name == $name)] |
  if length == 1 then .[0].id else error("Не найден статус") end' <<< "$FIELDS_JSON")
ISSUE_STATE=$(gh issue view "$N" --repo "$REPO" --json state --jq .state)
if [[ "$TARGET_STATUS" == "$DONE_STATUS" && "$ISSUE_STATE" != 'CLOSED' ]] ||
   [[ "$TARGET_STATUS" != "$DONE_STATUS" && "$ISSUE_STATE" == 'CLOSED' ]]; then
  echo 'Status противоречит состоянию issue' >&2; exit 1
fi
gh project item-edit --project-id "$PROJECT_ID" --id "$ITEM_ID" \
  --field-id "$STATUS_FIELD_ID" --single-select-option-id "$OPTION_ID"
gh project item-list "$PROJECT" --owner "$OWNER" --limit 1000 --format json |
  jq -e --arg id "$ITEM_ID" --arg status "$TARGET_STATUS" '[.items[] | select(.id == $id)] |
  if length == 1 and .[0].status == $status then .[0] | {id,status}
  else error("Изменение пока не подтверждено: повторить чтение, не запись") end'
```

При реальной задержке Auto-add не создавать новые тестовые issues. Ручное
восстановление с записью причины (не тест автодобавления):
`gh project item-add "$PROJECT" --owner "$OWNER" --url "$ISSUE_URL"`.
После закрытия issue сначала ждать штатного перехода в конечный статус, не маскировать
сломанное правило принудительной записью статуса.

## Назначение, закрытие и переоткрытие

Назначение себе не равно назначению пользователю: использовать подтверждённый
логин. Прежде чем взять неназначенную issue, проверить отсутствие ответственного;
`gh issue edit "$N" --repo "$REPO" --add-assignee "$ASSIGNEE"`, затем проверить
ровно одно назначение. Для передачи после согласования:

```bash
OLD_ASSIGNEE=$(gh issue view "$N" --repo "$REPO" --json assignees --jq \
  'if (.assignees | length) == 1 then .assignees[0].login else error("Нужен один текущий ответственный") end')
[[ "$NEW_ASSIGNEE" =~ ^[[:alnum:]][[:alnum:]-]*$ ]] || { echo 'Нужен один login' >&2; exit 1; }
test "$NEW_ASSIGNEE" != "$OLD_ASSIGNEE"
gh issue edit "$N" --repo "$REPO" --remove-assignee "$OLD_ASSIGNEE" --add-assignee "$NEW_ASSIGNEE"
gh issue view "$N" --repo "$REPO" --json assignees |
  jq -e --arg login "$NEW_ASSIGNEE" '.assignees | length == 1 and .[0].login == $login'
```

После полной приёмки, если профиль допускает явное закрытие: `gh issue close "$N" --repo "$REPO" --reason completed`.
**Для профиля приёмки всей спецификации сначала выполнить его процедуру, не заменять её этой командой.**
Согласованная отмена: `--reason "not planned"`, после комментария с причиной.
Переоткрытие после объяснения: `gh issue reopen "$N" --repo "$REPO"`.
В обоих случаях перечитать `state,stateReason` и карточку; переоткрытой issue
явно выставить соответствующий статус. Сам PR, мерж и выпуск здесь не выполняются.
