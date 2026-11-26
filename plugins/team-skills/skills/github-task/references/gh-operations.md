# Команды gh для issues и Projects

Использовать только для выбранного действия после проверки разрешений в SKILL.md.
Нужны `gh`, Bash и `jq`. Перед записью проверить поддержку флагов локальным
`gh ... --help`. Не включать вывод токенов, `set -x` и чтение файлов секретов.

## Учётка и права до операций

Сначала подтвердить `LOGIN` человека по контексту/профилю, затем сравнить с
`gh api user --jq .login`. Нельзя выбирать чужую учётку или выполнять
`gh auth switch`: переключение затронет другие репозитории. Проверить локальный
`gh auth token --help` на поддержку `--user`.

Прямой префикс: `GH_TOKEN="$(gh auth token --user <login>)" gh ...`.
Чтобы ошибка получения токена не привела к работе от чужой активной учётки,
использовать обёртку с проверкой результата:

```bash
gh_self() {
  local task_token
  task_token=$(env -u GH_TOKEN -u GITHUB_TOKEN gh auth token \
    --hostname github.com --user "$LOGIN") || return 1
  test -n "$task_token" || return 1
  GH_TOKEN="$task_token" command gh "$@"
}
gh_self api user --jq .login
gh_self auth status --hostname github.com
```

При отличающейся активной учётке **каждый** вызов `gh` ниже заменять на `gh_self`,
включая вызовы внутри `$()` и проверки после записи. Обёртка убирает влияние
унаследованных `GH_TOKEN`/`GITHUB_TOKEN` при выборе сохранённой учётки.
Токен существует только в памяти процесса: не печатать и не сохранять его в файлы,
не использовать `--show-token` или `set -x`.
Если своей учётки нет — остановиться и сообщить человеку.

Если `--user` отсутствует, человек может обновить gh либо самостоятельно войти
через `gh auth login --hostname github.com` с отдельным `GH_CONFIG_DIR`.
Этот каталог выбирает человек; он содержит секреты, агент его не читает.
Для **каждой** команды в этом варианте применять
`env -u GH_TOKEN -u GITHUB_TOKEN GH_CONFIG_DIR="$ACCOUNT_CONFIG_DIR" gh ...`,
включая `gh api user --jq .login` и `gh auth status`. Общую активную учётку не менять.

Перед любой операцией с доской проверить `gh auth status` выбранной учётки:
для чтения нужен `read:project` или `project`, для записи Status и других изменений
доски — `project`. Если scope отсутствует или его нельзя подтвердить, остановить
операцию и передать человеку команду `gh auth refresh -h github.com -s project`
для его учётки (в отдельном конфиге — с тем же `GH_CONFIG_DIR`). Код и подтверждение
вводит только человек. Затем повторить проверку login и scopes; без `project`
запись статуса запрещена. Права токена не заменяют доступ к самой доске/репозиторию.

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
явно выставить соответствующий статус. Мерж и выпуск здесь не выполняются; черновой PR для передачи — по рецепту ниже.


## Передать ветку / продолжить ветку

Имя новой ветки брать из правил целевого проекта. Если правила нет, предложить
`<type>/<issue>-<slug>`, где type — `feat`, `fix`, `docs` или `chore`.
Одна ветка — один владелец, совпадающий с единственным Assignee issue.
`BRANCH`, `BASE`, `REMOTE`, `PR_TITLE` и файлы ниже берутся из контекста проекта;
не угадывать базовую ветку или remote.

### Передающий

1. Согласовать нового владельца. Прочитать issue, существующий PR и его описание.
   Проверить правила целевого проекта и разрешение на push в рабочую ветку и
   создание PR. Если агенту это запрещено или действие не разрешено, подготовить
   локальный паспорт, показать оставшиеся шаги и попросить человека выполнить их.
   Не объявлять передачу завершённой до проверки ветки, PR, комментария и Assignee.
2. Проверить состояние ветки, коммитов и незакоммиченных изменений. Паспорт должен
   объяснять все остатки; локальные изменения не попадут к получателю сами.
   Коммит требует собственного разрешения. После разрешённого обычного push
   сверить удалённый head с последним переданным коммитом, записать полный SHA.

```bash
git status --short
git push "$REMOTE" "$BRANCH"
git rev-parse "$BRANCH"
git ls-remote --heads "$REMOTE" "refs/heads/$BRANCH"
```

3. Заполнить и прочитать `PASSPORT_FILE` по шаблону ниже. Указать точные файлы и
   ссылки, необходимые для продолжения, чтобы не повторять разведку репозитория.
   Если PR уже есть, обновить его описание с сохранением чужого текста, не создавать
   дубликат. Проверить `isDraft`: если существующий PR уже готов к review,
   согласовать возврат в draft (`gh pr ready --undo`) либо передать этот шаг
   человеку; не считать обычный PR черновиком. Для нового PR использовать черновик:

```bash
gh pr create --draft --repo "$REPO" --head "$BRANCH" --base "$BASE" \
  --title "$PR_TITLE" --body-file "$PASSPORT_FILE"
gh pr view "$BRANCH" --repo "$REPO" --json url,isDraft,headRefName,baseRefName,headRefOid,body
```

4. В просмотренном `REPORT_FILE` подготовить комментарий issue: ссылка на PR,
   ветка, последний push SHA, что передано, что осталось и согласованный получатель.
   Отправить `gh issue comment "$N" --repo "$REPO" --body-file "$REPORT_FILE"`.
   Заменить Assignee через рецепт назначения выше (ровно один новый владелец).
   Перечитать комментарии и назначение; статус менять только по профилю/поручению.
5. В конце каждой сессии обновлять паспорт в описании PR, сохраняя чужие правки:
   сначала `gh pr view`, затем `gh pr edit ... --body-file "$PASSPORT_FILE"`, затем
   перечитать результат. Если запись запрещена — подготовить обновление человеку.

### Паспорт передачи в описании PR

Не включать секреты и персональные данные. Для неприменимых пунктов писать «нет»;
проверка содержит команду, ожидаемый и фактический результат, включая падения.
Промежуточный PR ссылается на issue согласно политике закрытия проекта.

```markdown
## Branch handoff
- Branch and base: <branch>, <base>, <remote>
- Last pushed commit: <full SHA; any local-only work and where it is available>
- Issue: <URL>
- Done: <completed changes; exact file paths and relevant links>
- Remaining: <ordered next steps and acceptance gaps>
- How to verify and what it shows now: <commands; expected/actual results; evidence>
- Decisions and why: <choices and their reasons>
- Dead ends: <attempts that failed and why not to repeat them>
- Do not touch: <protected files, scope boundaries, concurrent work>
- Open questions: <unresolved questions and who can answer>
```

### Продолжающий

1. Проверить согласованную передачу и единственного Assignee. Прочитать описание
   PR с паспортом, issue и указанные в паспорте файлы/инструкции проекта. Не начинать
   повторную разведку всего репозитория. Если паспорта недостаточно, спросить
   недостающую конкретику в комментарии issue в пределах разрешений; до ответа
   не угадывать решения (при запрете комментария подготовить вопрос человеку).
2. Проверить чистоту своей рабочей копии, выбрать ту же ветку и подтянуть её.
   В новой копии создать локальную tracking-ветку для существующей удалённой.
   Не перезаписывать локальные изменения; при расхождении остановиться и выяснить
   причину. Не делать reset или force-push.

```bash
git status --short
git switch "$BRANCH"
git pull --ff-only "$REMOTE" "$BRANCH"
```

3. Сверить head с паспортом и текущим head PR. Продолжать поверх этой ветки,
   выполнять указанные проверки и обновлять паспорт в конце каждой сессии.
   Обычный push и обновление PR подчиняются тем же правилам проекта и разрешениям.
