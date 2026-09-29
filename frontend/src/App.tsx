import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, authenticate, clearSession, makeKey, request, type Dashboard, type Me, type Notification, type Plan, type Profile, type Program, type RuleResult } from './api';
import styles from './App.module.css';

const labels = { preliminary_match: 'Предварительно подходит', check_needed: 'Нужно уточнить условия', not_eligible: 'Не подходит по условиям', closed: 'Приём закрыт' };
const ruleLabels = { pass: 'Выполнено', fail: 'Не выполнено', unknown: 'Неизвестно', not_applicable: 'Не применяется' };
const nav = [['/', 'Главная'], ['/support', 'Поддержка'], ['/plans', 'Планы'], ['/profile', 'Профиль']] as const;
let supportScroll = 0;

function message(error: unknown) {
  if (typeof navigator !== 'undefined' && !navigator.onLine) return 'Нет подключения к сети. Проверьте интернет и повторите запрос.';
  return error instanceof ApiError && Object.keys(error.fieldErrors).length ? `${error.message}: ${Object.entries(error.fieldErrors).map(([field, detail]) => `${field} — ${detail}`).join('; ')}` : error instanceof Error ? error.message : 'Не удалось выполнить запрос';
}
function dateLabel(value: string | null) { return value ? new Intl.DateTimeFormat('ru-RU', { timeZone: 'Europe/Moscow', day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(value.length === 10 ? value + 'T12:00:00+03:00' : value)) : 'Срок не указан'; }
function dateTimeLabel(value: string) { return new Intl.DateTimeFormat('ru-RU', { timeZone: 'Europe/Moscow', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) + ' МСК'; }
function toUtc(value: string) { return new Date(value + ':00+03:00').toISOString(); }
function moscowToday() { const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date()); const part = (type: string) => parts.find(item => item.type === type)?.value || ''; return `${part('year')}-${part('month')}-${part('day')}`; }

function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const expired = error instanceof ApiError && error.status === 401;
  return <div className={styles.state} role="alert"><h2>Не удалось загрузить данные</h2><p>{message(error)}</p>{expired && <p>Откройте Mini App через MAX повторно для новой сессии.</p>}{retry && <button onClick={() => { if (expired) { clearSession(); authenticate().then(retry).catch(() => retry()); } else retry(); }}>{expired ? 'Повторный вход' : 'Повторить'}</button>}</div>;
}
function EmptyState({ title, children }: { title: string; children?: React.ReactNode }) {
  return <div className={styles.state}><h2>{title}</h2>{children}</div>;
}
function Skeleton() { return <div className={styles.skeleton} aria-label="Загрузка данных" />; }
function StatusLabel({ status }: { status: Program['match']['status'] }) { return <span className={`${styles.status} ${styles[status]}`}>{labels[status]}</span>; }
function DemoLabel() { return <span className={styles.demoLabel}>Демонстрационные данные</span>; }

export default function App() {
  const [ready, setReady] = useState(false);
  const [bootError, setBootError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const navigate = useNavigate();
  useEffect(() => {
    let active = true;
    authenticate().then(({ startParam }) => {
      if (active) {
        if (startParam === 'plans') navigate('/plans', { replace: true });
        else if (startParam === 'support') navigate('/support', { replace: true });
        else if (startParam && /^plan_[a-fA-F0-9_]{36}$/.test(startParam)) navigate(`/plans/${startParam.slice(5).replaceAll('_', '-')}`, { replace: true });
        setReady(true); setBootError(null);
      }
    }).catch(error => { if (active) setBootError(error); });
    return () => { active = false; };
  }, [attempt, navigate]);
  if (bootError) return <div className={styles.boot}><h1>ДЕЛО</h1><ErrorState error={bootError} retry={() => { setBootError(null); setAttempt(value => value + 1); }} /><p>Для рабочего входа откройте мини-приложение через бота MAX.</p></div>;
  if (!ready) return <div className={styles.boot}><h1>ДЕЛО</h1><Skeleton /></div>;
  return <AppContent />;
}

function AppContent() {
  const me = useQuery({ queryKey: ['me'], queryFn: () => request<Me>('/me') });
  const location = useLocation();
  const active = location.pathname.startsWith('/support') ? '/support' : location.pathname.startsWith('/plans') ? '/plans' : location.pathname.startsWith('/profile') ? '/profile' : '/';
  return <div className={styles.shell}>
    <aside className={styles.sidebar}>
      <Link className={styles.brand} to="/">ДЕЛО<span>Поддержка бизнеса</span></Link>
      <nav aria-label="Основная навигация">{nav.map(([path, text]) => <NavLink className={active === path ? styles.activeNav : ''} key={path} to={path}>{text}</NavLink>)}</nav>
      <div className={styles.sidebarFoot}>Санкт-Петербург · пилотный сегмент</div>
    </aside>
    <div className={styles.content}>
      <header className={styles.topbar}><Link className={styles.mobileBrand} to="/">ДЕЛО</Link><span>{me.data?.display_name || 'Поддержка бизнеса'}</span></header>
      <main className={styles.main}>
        <div className={styles.demoBanner}><DemoLabel /><span>Учебные программы. Условия требуют проверки перед обращением к оператору.</span></div>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/support" element={<Support />} />
          <Route path="/support/:id" element={<Support />} />
          <Route path="/plans" element={<Plans />} />
          <Route path="/plans/:id" element={<PlanDetail mode={me.data?.mode} />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="*" element={<EmptyState title="Страница не найдена"><Link to="/">На главную</Link></EmptyState>} />
        </Routes>
      </main>
    </div>
    <nav className={styles.mobileNav} aria-label="Основная навигация">{nav.map(([path, text]) => <NavLink className={active === path ? styles.activeNav : ''} key={path} to={path}>{text}</NavLink>)}</nav>
  </div>;
}

function ProgramCard({ program, search = '' }: { program: Program; search?: string }) {
  return <article className={styles.card}>
    <div className={styles.cardHead}><StatusLabel status={program.match.status} />{program.provenance.data_kind === 'synthetic' && <DemoLabel />}</div>
    <h3>{program.title}</h3>
    <p className={styles.muted}>{program.benefit_type} · {program.amount_text || 'Сумма не указана'}</p>
    <p>До: {dateLabel(program.deadline)}</p>
    <p className={styles.muted}>Проверено {program.match.checked_count} из {program.match.required_count} обязательных условий</p>
    <Link onClick={() => { supportScroll = window.scrollY; }} to={`/support/${program.id}${search}`} className={styles.textLink}>Подробнее <span aria-hidden>→</span></Link>
  </article>;
}

function Home() {
  const query = useQuery({ queryKey: ['dashboard'], queryFn: () => request<Dashboard>('/dashboard') });
  if (query.isPending) return <Skeleton />;
  if (query.error) return <ErrorState error={query.error} retry={() => query.refetch()} />;
  const data = query.data;
  if (!data.profile) return <section><h1>Поддержка для вашего бизнеса</h1><p className={styles.lead}>Заполните короткий профиль, чтобы увидеть применимые учебные программы и подготовить план.</p><Link className={styles.primaryLink} to="/profile">Заполнить профиль</Link></section>;
  return <section><PageHeader title={`Здравствуйте, ${data.profile.business_name}`} subtitle="Ваши рекомендации и ближайшие действия" />
    <div className={styles.homeGrid}>
      <div><h2>Рекомендуем посмотреть</h2>{data.recommendations.length ? data.recommendations.map(program => <ProgramCard key={program.id} program={program} />) : <EmptyState title="Рекомендаций пока нет"><p>Проверьте регион, цель и другие данные профиля.</p><Link to="/profile">Изменить профиль</Link></EmptyState>}<Link className={styles.textLink} to="/support">Весь каталог →</Link></div>
      <div><h2>Активный план</h2><div className={styles.card}><p className={styles.muted}>Активных планов</p><strong className={styles.bigNumber}>{data.active_plans}</strong>{data.next_item ? <><p>Ближайшее действие: {data.next_item.title}</p><Link className={styles.textLink} to={`/plans/${data.next_item.plan_id}`}>Открыть план →</Link></> : <p>Незавершённых действий пока нет.</p>}</div></div>
    </div>
  </section>;
}

function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) { return <div className={styles.pageHeader}><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>; }

function Support() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const search = params.get('search') || '';
  const status = params.get('status') || '';
  const purpose = params.get('purpose') || '';
  const query = useQuery({ queryKey: ['programs', search, status, purpose], queryFn: () => request<Program[]>(`/programs?${new URLSearchParams({ search, ...(status ? { status } : {}), ...(purpose ? { purpose } : {}) })}`) });
  const detail = useQuery({ queryKey: ['program', id], queryFn: () => request<Program>(`/programs/${id}`), enabled: !!id });
  const navigate = useNavigate();
  useEffect(() => { if (!id && supportScroll) requestAnimationFrame(() => window.scrollTo(0, supportScroll)); }, [id]);
  function update(key: string, value: string) { const copy = new URLSearchParams(params); value ? copy.set(key, value) : copy.delete(key); setParams(copy); }
  return <section>
    <PageHeader title="Поддержка" subtitle="Выберите программу и проверьте условия" />
    <div className={styles.filters}>
      <label>Поиск<input value={search} onChange={event => update('search', event.target.value)} placeholder="Название программы" /></label>
      <label>Статус<select value={status} onChange={event => update('status', event.target.value)}><option value="">Все</option><option value="preliminary_match">Предварительно подходит</option><option value="check_needed">Нужно уточнить</option><option value="not_eligible">Не подходит</option><option value="closed">Закрыт</option></select></label>
      <label>Цель<select value={purpose} onChange={event => update('purpose', event.target.value)}><option value="">Все цели</option><option value="equipment">Оборудование</option><option value="development">Развитие</option><option value="digital">Цифровизация</option></select></label>
    </div>
    <div className={`${styles.supportGrid} ${id ? styles.hasDetail : ''}`}>
      <div className={styles.programList}>
        {query.isPending ? <Skeleton /> : query.error ? <ErrorState error={query.error} retry={() => query.refetch()} /> : query.data?.length ? query.data.map(program => <ProgramCard key={program.id} program={program} search={locationSearch(params)} />) : <EmptyState title="По этим фильтрам программ нет"><p>Измените поиск или фильтры.</p></EmptyState>}
      </div>
      <div className={styles.programDetail}>
        {id ? detail.isPending ? <Skeleton /> : detail.error ? <ErrorState error={detail.error} retry={() => detail.refetch()} /> : detail.data && <ProgramDetail program={detail.data} back={() => navigate(`/support${locationSearch(params)}`)} /> : <EmptyState title="Выберите программу"><p>Условия и список документов появятся здесь.</p></EmptyState>}
      </div>
    </div>
  </section>;
}
function locationSearch(params: URLSearchParams) { const value = params.toString(); return value ? `?${value}` : ''; }

function Rule({ rule }: { rule: RuleResult }) {
  return <li className={styles.rule}><span className={`${styles.ruleBadge} ${styles[rule.outcome]}`}>{ruleLabels[rule.outcome]}</span><span>{rule.explanation}{rule.children && <ul>{rule.children.map((child, index) => <Rule key={index} rule={child} />)}</ul>}</span></li>;
}

function ProgramDetail({ program, back }: { program: Program; back: () => void }) {
  const [due, setDue] = useState('');
  const [reminders, setReminders] = useState(false);
  const [reminderAt, setReminderAt] = useState('');
  const [saveError, setSaveError] = useState('');
  const key = useRef(makeKey());
  const navigate = useNavigate();
  const client = useQueryClient();
  const me = useQuery({ queryKey: ['me'], queryFn: () => request<Me>('/me') });
  const create = useMutation({ mutationFn: () => request<Plan>('/plans', {
    method: 'POST', headers: { 'Idempotency-Key': key.current },
    body: JSON.stringify({ program_id: program.id, due_at: toUtc(due), reminders_enabled: reminders, reminder_at: reminderAt ? toUtc(reminderAt) : null }),
  }), onSuccess: plan => { client.invalidateQueries({ queryKey: ['plans'] }); client.invalidateQueries({ queryKey: ['dashboard'] }); navigate(`/plans/${plan.id}`); }, onError: error => setSaveError(message(error)) });
  function changed(setter: (value: string) => void, value: string) { setter(value); key.current = makeKey(); setSaveError(''); }
  const allowed = ['preliminary_match', 'check_needed'].includes(program.match.status);
  return <article className={styles.detailCard}>
    <button className={styles.backButton} onClick={back}>← К каталогу</button>
    <div className={styles.cardHead}><StatusLabel status={program.match.status} />{program.provenance.data_kind === 'synthetic' && <DemoLabel />}</div>
    <h2>{program.title}</h2><p>{program.description}</p>
    <div className={styles.infoGrid}><div><strong>Оператор</strong><span>{program.operator_name}</span></div><div><strong>Тип помощи</strong><span>{program.benefit_type}</span></div><div><strong>Сумма</strong><span>{program.amount_text || 'Не указана'}{program.amount_text && ' (верхний предел, не гарантия)'}</span></div><div><strong>Срок приёма</strong><span>{dateLabel(program.deadline)} · МСК</span></div></div>
    <h3>Проверка условий</h3><p className={styles.muted}>Проверено {program.match.checked_count} из {program.match.required_count} обязательных условий. Это предварительная оценка по вашим данным.</p>
    <ul className={styles.rules}>{program.match.rules.map((rule, index) => <Rule key={index} rule={rule} />)}</ul>
    <ClarifyConditions program={program} />
    <h3>Что потребуется</h3><ul>{program.documents?.map(item => <li key={item}>{item}</li>)}</ul>
    <p className={styles.source}>Источник: {program.provenance.source_title}. {program.provenance.checked_at ? `Проверено ${dateLabel(program.provenance.checked_at)}.` : 'Официальная проверка не проводилась.'} {program.provenance.source_url && /^https?:\/\//.test(program.provenance.source_url) && <a href={program.provenance.source_url} target="_blank" rel="noreferrer">Открыть источник</a>}</p>
    {allowed ? <form className={styles.planForm} onSubmit={event => { event.preventDefault(); create.mutate(); }}>
      <h3>Создать план подготовки</h3>
      <label>Дата подготовки · МСК<input type="datetime-local" required value={due} onChange={event => changed(setDue, event.target.value)} /></label>
      <label className={styles.checkbox}><input type="checkbox" checked={reminders} disabled={!me.data?.bot_started} onChange={event => { setReminders(event.target.checked); key.current = makeKey(); }} />Напомнить через MAX</label>
      {!me.data?.bot_started && <p className={styles.muted}>Для напоминаний сначала запустите бота MAX.</p>}
      {reminders && <label>Время напоминания · МСК (необязательно)<input type="datetime-local" value={reminderAt} onChange={event => changed(setReminderAt, event.target.value)} /></label>}
      <p className={styles.muted}>Если время не выбрано, напомним за день до даты подготовки.</p>
      {saveError && <p className={styles.errorText} role="alert">{saveError}</p>}
      <button className={styles.primaryButton} disabled={create.isPending}>{create.isPending ? 'Сохраняем…' : 'Создать план подготовки'}</button>
    </form> : <div className={styles.state}><strong>Новый план недоступен</strong><p>{program.match.status === 'closed' ? 'Приём закрыт или срок истёк.' : 'Есть обязательное условие, которое не выполнено.'} Существующие планы можно открыть в разделе «Планы».</p></div>}
  </article>;
}

function ClarifyConditions({ program }: { program: Program }) {
  const fields = new Set(program.match.rules.flatMap(rule => [rule.field, ...(rule.children?.map(child => child.field) || [])]));
  const hasDebt = fields.has('tax_debt');
  const hasRevenue = fields.has('revenue');
  const profile = useQuery({ queryKey: ['profile'], queryFn: () => request<Profile | null>('/profile') });
  const client = useQueryClient();
  const [taxDebt, setTaxDebt] = useState<Profile['tax_debt']>('unknown');
  const [revenue, setRevenue] = useState('');
  const [loadedVersion, setLoadedVersion] = useState<number | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (profile.data && profile.data.version !== loadedVersion) {
      setTaxDebt(profile.data.tax_debt);
      setRevenue(profile.data.revenue === null ? '' : String(profile.data.revenue));
      setLoadedVersion(profile.data.version);
    }
  }, [profile.data, loadedVersion]);
  const save = useMutation({
    mutationFn: () => request<Profile>('/profile', { method: 'PUT', body: JSON.stringify({ ...profile.data, tax_debt: taxDebt, revenue: revenue === '' ? null : Number(revenue), version: profile.data?.version }) }),
    onSuccess: () => {
      setError('');
      client.invalidateQueries({ queryKey: ['profile'] });
      client.invalidateQueries({ queryKey: ['program', program.id] });
      client.invalidateQueries({ queryKey: ['programs'] });
      client.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: failure => setError(message(failure)),
  });
  if (!hasDebt && !hasRevenue) return null;
  return <div className={styles.clarify}>
    <h3>Уточнить данные для этой программы</h3>
    <p className={styles.muted}>Ответы по вашим сведениям. ДЕЛО не проверяет их автоматически.</p>
    {profile.isPending ? <Skeleton /> : profile.error ? <ErrorState error={profile.error} retry={() => profile.refetch()} /> : !profile.data ? <Link to="/profile">Сначала заполните профиль</Link> : <form onSubmit={event => { event.preventDefault(); save.mutate(); }}>
      {hasDebt && <label>Есть налоговая задолженность?<select value={taxDebt} onChange={event => setTaxDebt(event.target.value as Profile['tax_debt'])}><option value="unknown">Не знаю</option><option value="no">Нет, по моим данным</option><option value="yes">Да</option></select></label>}
      {hasRevenue && <label>Выручка, ₽<input type="number" min="0" value={revenue} onChange={event => setRevenue(event.target.value)} placeholder="Неизвестно" /></label>}
      {error && <p className={styles.errorText} role="alert">{error} {error.includes('другом устройстве') && <button type="button" onClick={() => { setLoadedVersion(null); profile.refetch(); }}>Загрузить актуальные данные</button>}</p>}
      <button disabled={save.isPending}>Сохранить уточнение</button>
    </form>}
  </div>;
}

function Plans() {
  const query = useQuery({ queryKey: ['plans'], queryFn: () => request<Plan[]>('/plans') });
  if (query.isPending) return <Skeleton />;
  if (query.error) return <ErrorState error={query.error} retry={() => query.refetch()} />;
  return <section><PageHeader title="Планы" subtitle="Чек-листы подготовки к программам" />{query.data?.length ? <div className={styles.planCards}>{query.data.map(plan => <article key={plan.id} className={styles.card}><span className={styles.muted}>{plan.status === 'active' ? 'Активен' : plan.status === 'completed' ? 'Завершён' : 'Отменён'}</span><h2>{plan.program_snapshot.title}</h2><p>Подготовить до {dateTimeLabel(plan.due_at)}</p><p>Готово {plan.progress}%</p><progress value={plan.progress} max="100" /><Link className={styles.textLink} to={`/plans/${plan.id}`}>Открыть план →</Link></article>)}</div> : <EmptyState title="Планов пока нет"><Link to="/support">Найти программу</Link></EmptyState>}</section>;
}

function PlanDetail({ mode }: { mode?: 'demo' | 'max' }) {
  const { id } = useParams();
  const query = useQuery({ queryKey: ['plan', id], queryFn: () => request<Plan>(`/plans/${id}`), enabled: !!id });
  const notices = useQuery({ queryKey: ['notifications', id], queryFn: () => request<Notification[]>(`/plans/${id}/notifications`), enabled: !!id });
  const client = useQueryClient();
  const [actionError, setActionError] = useState('');
  const [newDue, setNewDue] = useState('');
  const [newAction, setNewAction] = useState('');
  const [confirmation, setConfirmation] = useState<'completed' | 'cancelled' | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const closeConfirmation = () => { setConfirmation(null); requestAnimationFrame(() => trigger.current?.focus()); };
  const refresh = () => { client.invalidateQueries({ queryKey: ['plan', id] }); client.invalidateQueries({ queryKey: ['plans'] }); client.invalidateQueries({ queryKey: ['notifications', id] }); client.invalidateQueries({ queryKey: ['dashboard'] }); };
  const itemMutation = useMutation({ mutationFn: (item: Plan['items'][number]) => request<Plan>(`/plans/${id}/items/${item.id}`, { method: 'PATCH', body: JSON.stringify({ version: query.data!.version, status: item.status === 'done' ? 'todo' : 'done' }) }), onSuccess: refresh, onError: error => { setActionError(message(error)); if (error instanceof ApiError && error.status === 409) refresh(); } });
  const planMutation = useMutation({ mutationFn: (change: object) => request<Plan>(`/plans/${id}`, { method: 'PATCH', body: JSON.stringify({ version: query.data!.version, ...change }) }), onSuccess: () => { setActionError(''); setNewDue(''); refresh(); }, onError: error => { setActionError(message(error)); if (error instanceof ApiError && error.status === 409) refresh(); } });
  const addAction = useMutation({ mutationFn: () => request<Plan>(`/plans/${id}/items`, { method: 'POST', body: JSON.stringify({ version: query.data!.version, title: newAction.trim() }) }), onSuccess: () => { setNewAction(''); setActionError(''); refresh(); }, onError: error => { setActionError(message(error)); if (error instanceof ApiError && error.status === 409) refresh(); } });
  const demo = useMutation({ mutationFn: () => request<{ status: string }>('/demo/reminder', { method: 'POST', body: JSON.stringify({ plan_id: id }) }), onSuccess: refresh, onError: error => setActionError(message(error)) });
  if (query.isPending) return <Skeleton />;
  if (query.error) return <ErrorState error={query.error} retry={() => query.refetch()} />;
  const plan = query.data!;
  return <section><Link className={styles.textLink} to="/plans">← Все планы</Link><PageHeader title={plan.program_snapshot.title} subtitle="План подготовки" />
    {plan.program_changed && <div className={styles.demoBanner}>Условия программы изменились после создания плана. Сверьте актуальную карточку программы; отмеченные пункты сохранены.</div>}
    <div className={styles.planGrid}>
      <div className={styles.card}><h2>Чек-лист</h2><p className={styles.muted}>Отметка означает наличие документа или выполненное действие, а не проверку содержания.</p>
        {plan.items.length ? <ul className={styles.checklist}>{plan.items.map(item => <li key={item.id}><label><input type="checkbox" checked={item.status === 'done'} disabled={plan.status !== 'active' || itemMutation.isPending} onChange={() => { setActionError(''); itemMutation.mutate(item); }} /><span>{item.title}</span></label><small>{item.kind === 'clarification' ? 'Уточнение' : item.kind === 'document' ? 'Документ' : 'Действие'}</small></li>)}</ul> : <EmptyState title="Добавьте действие" />}
        {plan.status === 'active' && <form className={styles.addAction} onSubmit={event => { event.preventDefault(); if (newAction.trim()) addAction.mutate(); }}><label>Своё действие<input maxLength={240} value={newAction} onChange={event => setNewAction(event.target.value)} placeholder="Например, связаться с оператором" /></label><button disabled={addAction.isPending || !newAction.trim()}>Добавить</button></form>}
      </div>
      <div><div className={styles.card}><h2>Срок и прогресс</h2><p>{dateTimeLabel(plan.due_at)}</p><progress value={plan.progress} max="100" /><p>{plan.progress}% выполнено</p>
        {plan.status === 'active' && <><form onSubmit={event => { event.preventDefault(); planMutation.mutate({ due_at: toUtc(newDue) }); }}><label>Перенести дату · МСК<input type="datetime-local" required value={newDue} onChange={event => setNewDue(event.target.value)} /></label><button disabled={planMutation.isPending}>Сохранить дату</button></form><button className={styles.secondaryButton} disabled={planMutation.isPending} onClick={event => { trigger.current = event.currentTarget; setConfirmation('completed'); }}>Завершить план</button><button className={styles.dangerButton} disabled={planMutation.isPending} onClick={event => { trigger.current = event.currentTarget; setConfirmation('cancelled'); }}>Отменить план</button></>}
      </div>
      <div className={styles.card}><h2>Напоминания</h2><p>{plan.reminders_enabled ? 'Включены' : 'Выключены'}</p>{plan.status === 'active' && <button onClick={() => planMutation.mutate({ reminders_enabled: !plan.reminders_enabled })}>{plan.reminders_enabled ? 'Отключить' : 'Включить'} напоминания</button>}
        {mode === 'demo' && plan.status === 'active' && <button className={styles.secondaryButton} disabled={demo.isPending} onClick={() => demo.mutate()}>Тестовое напоминание через 60 секунд</button>}
        {notices.isPending ? <Skeleton /> : notices.error ? <ErrorState error={notices.error} retry={() => notices.refetch()} /> : notices.data?.length ? <ul className={styles.noticeList}>{notices.data.map(notice => <li key={notice.id}>{notice.type === 'confirmation' ? 'Подтверждение' : 'Напоминание'} · {dateTimeLabel(notice.scheduled_at)} · {notice.status === 'simulated' ? 'Симуляция' : notice.status === 'sent' ? 'Принято API MAX' : notice.status === 'pending' ? 'Ожидает отправки' : notice.status === 'uncertain' ? 'Результат неизвестен' : notice.status === 'cancelled' ? 'Отменено' : 'Ошибка'}</li>)}</ul> : <p className={styles.muted}>Уведомлений пока нет.</p>}
      </div></div>
    </div>
    {confirmation && <ConfirmDialog title={confirmation === 'completed' ? 'Завершить план?' : 'Отменить план?'} description="Будущие напоминания будут отменены. Отмеченные пункты останутся в истории." onCancel={closeConfirmation} onConfirm={() => { planMutation.mutate({ status: confirmation }); closeConfirmation(); }} />}
    {actionError && <div className={styles.errorText} role="alert">{actionError} <button onClick={() => { setActionError(''); refresh(); }}>Загрузить актуальные данные</button></div>}
  </section>;
}

function ConfirmDialog({ title, description, onCancel, onConfirm }: { title: string; description: string; onCancel: () => void; onConfirm: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); return () => { dialog.current?.close(); }; }, []);
  return <dialog ref={dialog} className={styles.dialog} aria-labelledby="confirm-title" onCancel={event => { event.preventDefault(); onCancel(); }}>
    <h2 id="confirm-title">{title}</h2><p>{description}</p><div className={styles.formActions}><button onClick={onCancel}>Назад</button><button className={styles.primaryButton} onClick={onConfirm}>Подтвердить</button></div>
  </dialog>;
}

const emptyProfile = { business_name: '', legal_form: 'ip', region_code: 'spb', industry_code: '', employee_count: 0, registration_date: '', purpose_code: 'equipment', tax_debt: 'unknown', revenue: '' };
function ProfilePage() {
  const query = useQuery({ queryKey: ['profile'], queryFn: () => request<Profile | null>('/profile') });
  const client = useQueryClient();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState({ ...emptyProfile });
  const [loadedVersion, setLoadedVersion] = useState<number | null>(null);
  const [saveError, setSaveError] = useState('');
  useEffect(() => { if (query.data && loadedVersion === null) { setDraft({ ...query.data, revenue: query.data.revenue === null ? '' : String(query.data.revenue) } as typeof emptyProfile); setLoadedVersion(query.data.version); } }, [query.data, loadedVersion]);
  const save = useMutation({ mutationFn: () => request<Profile>('/profile', { method: 'PUT', body: JSON.stringify({ ...draft, employee_count: Number(draft.employee_count), revenue: draft.revenue === '' ? null : Number(draft.revenue), version: loadedVersion }) }), onSuccess: () => { client.invalidateQueries({ queryKey: ['profile'] }); client.invalidateQueries({ queryKey: ['dashboard'] }); client.invalidateQueries({ queryKey: ['programs'] }); navigate('/'); }, onError: error => { setSaveError(message(error)); if (error instanceof ApiError && error.status === 409) query.refetch(); } });
  if (query.isPending) return <Skeleton />;
  if (query.error) return <ErrorState error={query.error} retry={() => query.refetch()} />;
  return <section><PageHeader title={query.data ? 'Профиль бизнеса' : 'Расскажите о бизнесе'} subtitle="Все сведения вводите вы. Реестры и задолженность автоматически не проверяются." />
    <div className={styles.profileCard}><p className={styles.muted}>Шаг {step + 1} из 2</p><progress value={step + 1} max="2" />
      <form onSubmit={event => { event.preventDefault(); if (step === 0) setStep(1); else save.mutate(); }}>
        {step === 0 ? <><label>Название бизнеса<input required maxLength={120} value={draft.business_name} onChange={event => setDraft({ ...draft, business_name: event.target.value })} /></label>
          <label>Форма<select value={draft.legal_form} onChange={event => setDraft({ ...draft, legal_form: event.target.value })}><option value="ip">ИП</option><option value="ooo">ООО</option></select></label>
          <label>Регион<select value={draft.region_code} onChange={event => setDraft({ ...draft, region_code: event.target.value })}><option value="spb">Санкт-Петербург</option><option value="other">Другой регион</option></select></label>
          <label>Код отрасли<input required maxLength={60} value={draft.industry_code} onChange={event => setDraft({ ...draft, industry_code: event.target.value })} placeholder="Например, services" /></label>
          <label>Число сотрудников<input required type="number" min="0" max="30" value={draft.employee_count} onChange={event => setDraft({ ...draft, employee_count: Number(event.target.value) })} /></label>
          <label>Дата регистрации<input required type="date" max={moscowToday()} value={draft.registration_date} onChange={event => setDraft({ ...draft, registration_date: event.target.value })} /></label>
        </> : <><label>Цель<select value={draft.purpose_code} onChange={event => setDraft({ ...draft, purpose_code: event.target.value })}><option value="equipment">Оборудование</option><option value="development">Развитие</option><option value="digital">Цифровизация</option></select></label>
          <p className={styles.muted}>Дополнительные вопросы появятся только у программы, для которой нужны эти сведения.</p>
        </>}
        {saveError && <p className={styles.errorText} role="alert">{saveError} {saveError.includes('другом устройстве') && <button type="button" onClick={async () => { const result = await query.refetch(); if (result.data) { setDraft({ ...result.data, revenue: result.data.revenue === null ? '' : String(result.data.revenue) } as typeof emptyProfile); setLoadedVersion(result.data.version); setSaveError(''); } }}>Загрузить актуальные данные</button>}</p>}
        <div className={styles.formActions}>{step > 0 && <button type="button" onClick={() => setStep(0)}>Назад</button>}<button className={styles.primaryButton} disabled={save.isPending}>{step === 0 ? 'Продолжить' : save.isPending ? 'Сохраняем…' : 'Сохранить профиль'}</button></div>
      </form>
    </div>
  </section>;
}
