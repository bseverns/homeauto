<script lang="ts">
  import { onMount } from 'svelte'
  import { createWorldStateRefresh, evidenceAnchor, explicitState, sourceMessage, type WorldState } from './model'

  let world: WorldState | null = null
  let error = ''
  let loading = true
  let refreshing = false

  const refreshController = createWorldStateRefresh({
    fetcher: () => fetch('/api/v1/world-state', { headers: { Accept: 'application/json' } }),
    onUpdate: (state) => {
      world = state.world
      error = state.error
      loading = state.loading
      refreshing = state.refreshing
    },
  })

  onMount(() => {
    void refreshController.start()
    return () => refreshController.stop()
  })

  const text = (value: unknown) => typeof value === 'string' ? value : ''
  const list = (value: unknown) => Array.isArray(value) ? value.map(String) : []
  const hasEvidence = (id: string) => world?.evidence_index.some((item) => item.id === id) ?? false
  const recentTransitions = () => world?.transitions.slice(-8).reverse() ?? []
</script>

<svelte:head>
  <meta name="description" content="Read-only Homeauto coordination dashboard" />
</svelte:head>

<main>
  <header class="masthead">
    <div>
      <p class="eyebrow">HOMEAUTO / READ-ONLY</p>
      <h1>Control Deck</h1>
      <p class="lede">A quiet view of what is known, what is possible, and what remains uncertain.</p>
    </div>
    {#if world}
      <div class="source-tools">
      <div class:warning={world.source.freshness !== 'current'} class="source-badge">
        <span class="signal"></span>
        <div>
          <strong>{explicitState(world.source.freshness)}</strong>
          <small>{sourceMessage(world.source)}</small>
        </div>
      </div>
      <button class="refresh" disabled={refreshing} on:click={() => refreshController.refresh()}>
        {refreshing ? 'Refreshing…' : 'Refresh state'}
      </button>
      </div>
    {/if}
  </header>

  {#if loading}
    <section class="notice" aria-live="polite">Reading deterministic coordination state…</section>
  {:else if error && !world}
    <section class="notice error" role="alert">
      <strong>Control Deck unavailable</strong>
      <span>{error}. No state has been inferred.</span>
    </section>
  {:else if world}
    {#if error}
      <section class="notice error" role="alert">
        <strong>Refresh failed</strong>
        <span>{error}. Showing the last successful snapshot; no replacement state was inferred.</span>
      </section>
    {/if}
    <section class="summary" aria-label="Snapshot summary">
      <div><span>{world.opportunities.length}</span><small>opportunities</small></div>
      <div><span>{world.machines.length}</span><small>machines</small></div>
      <div><span>{world.transitions.length}</span><small>retained transitions</small></div>
      <div><span>{world.evidence_index.length}</span><small>safe evidence records</small></div>
    </section>

    <div class="layout">
      <section class="primary" aria-labelledby="opportunities-heading">
        <div class="section-heading">
          <div>
            <p class="eyebrow">PRESENT CONDITIONS</p>
            <h2 id="opportunities-heading">Opportunities</h2>
          </div>
          <span class="timestamp">generated {world.generated_at}</span>
        </div>

        {#if world.opportunities.length === 0}
          <div class="empty">
            <strong>No current opportunities</strong>
            <span>The source returned an empty set. Nothing has been inferred to fill it.</span>
          </div>
        {:else}
          <div class="cards">
            {#each world.opportunities as opportunity}
              <article class="opportunity">
                <div class="card-top">
                  <span class="state state-{opportunity.state}">{opportunity.state.replaceAll('_', ' ')}</span>
                  <code>{opportunity.action_id}</code>
                </div>
                <h3>{text(opportunity.action.project) || opportunity.project_id || 'Unnamed project'}</h3>
                <p class="action">{text(opportunity.action.next_action) || 'No action text supplied'}</p>

                <div class="meta">
                  <span>effort <b>{explicitState(opportunity.action.effort)}</b></span>
                  <span>capacity <b>{explicitState(opportunity.capacity?.fit_status)}</b></span>
                  <span>queue <b>{explicitState(opportunity.action.queue)}</b></span>
                </div>

                {#if (opportunity.affordances.missing ?? []).length > 0}
                  <p class="missing"><b>Missing:</b> {(opportunity.affordances.missing ?? []).join(', ')}</p>
                {/if}

                <details>
                  <summary>Why this state</summary>
                  <ul class="checks">
                    {#each opportunity.why as check}
                      <li>
                        <span class="result result-{check.result}">{check.result}</span>
                        <div>
                          <b>{check.check.replaceAll('_', ' ')}</b>
                          <p>{check.detail}</p>
                          {#if check.source_ids.length}
                            <div class="evidence-links">
                              {#each check.source_ids as id}
                                {#if hasEvidence(id)}
                                  <a href="#{evidenceAnchor(id)}">{id}</a>
                                {:else}
                                  <span title="Evidence detail is not present in the safe index">{id}</span>
                                {/if}
                              {/each}
                            </div>
                          {/if}
                        </div>
                      </li>
                    {/each}
                  </ul>
                </details>
              </article>
            {/each}
          </div>
        {/if}
      </section>

      <aside aria-labelledby="sources-heading">
        <div class="section-heading compact">
          <div><p class="eyebrow">PROVENANCE</p><h2 id="sources-heading">Sources</h2></div>
        </div>
        <div class="source-list">
          {#each Object.entries(world.inputs) as [name, input]}
            <div>
              <strong>{name}</strong>
              <span>{input.contract?.name ?? 'unavailable contract'}</span>
              <small>{input.generated_at ?? 'freshness unknown'}</small>
            </div>
          {/each}
        </div>
        <div class="boundaries">
          <h3>Authority boundaries</h3>
          <ul>{#each world.boundaries as boundary}<li>{boundary}</li>{/each}</ul>
        </div>
      </aside>
    </div>

    <section aria-labelledby="machines-heading">
      <div class="section-heading">
        <div><p class="eyebrow">PHYSICAL SYSTEMS</p><h2 id="machines-heading">Machines</h2></div>
      </div>
      {#if world.machines.length === 0}
        <div class="empty">No registered dashboard machines.</div>
      {:else}
        <div class="machine-grid">
          {#each world.machines as machine}
            <article class="machine">
              <div class="machine-head">
                <h3>{machine.label}</h3>
                <span class="state state-{machine.readiness}">{explicitState(machine.readiness)}</span>
              </div>
              <dl>
                <div><dt>Lifecycle</dt><dd>{explicitState(machine.lifecycle)}</dd></div>
                <div><dt>Telemetry</dt><dd>{explicitState(machine.runtime)}</dd></div>
                <div><dt>Freshness</dt><dd>{explicitState(machine.freshness)}</dd></div>
              </dl>
              <p class="capabilities">{machine.capabilities?.join(' · ') || 'no declared capabilities'}</p>
              {#if machine.why?.length}
                <details><summary>Evidence and reason</summary><ul>{#each machine.why as reason}<li>{reason}</li>{/each}</ul></details>
              {/if}
            </article>
          {/each}
        </div>
      {/if}
    </section>

    <div class="lower-grid">
      <section aria-labelledby="transitions-heading">
        <div class="section-heading compact"><div><p class="eyebrow">CHANGE LOG</p><h2 id="transitions-heading">Recent transitions</h2></div></div>
        {#if recentTransitions().length === 0}
          <div class="empty">No retained transitions.</div>
        {:else}
          <ol class="timeline">
            {#each recentTransitions() as transition}
              <li>
                <time>{transition.changed_at ?? 'time unknown'}</time>
                <strong>{transition.situation_id}</strong>
                <span>{transition.from ?? 'unknown'} → {transition.to ?? 'unknown'}</span>
                {#if transition.cause}<small>{transition.cause}</small>{/if}
              </li>
            {/each}
          </ol>
        {/if}
      </section>

      <section aria-labelledby="evidence-heading">
        <div class="section-heading compact"><div><p class="eyebrow">SAFE INDEX</p><h2 id="evidence-heading">Evidence</h2></div></div>
        {#if world.evidence_index.length === 0}
          <div class="empty">No safe evidence details are available.</div>
        {:else}
          <ul class="evidence-index">
            {#each world.evidence_index as evidence}
              <li id={evidenceAnchor(evidence.id)}>
                <code>{evidence.id}</code>
                <strong>{evidence.source?.name ?? 'unknown source'}</strong>
                <span>{evidence.source?.semantic ?? 'unknown semantic'} · {evidence.freshness?.status ?? 'unknown freshness'}</span>
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    </div>
  {/if}
</main>

<style>
  :global(*) { box-sizing: border-box; }
  :global(html) { color-scheme: dark; background: #0c100f; }
  :global(body) { margin: 0; min-width: 320px; color: #e9efeb; font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif; background: radial-gradient(circle at 80% 0%, #183128 0, transparent 34rem), #0c100f; }
  :global(a) { color: #9ad9be; }
  :global(code) { overflow-wrap: anywhere; color: #aebdb6; font-size: .72rem; }
  main { width: min(1440px, 100%); margin: 0 auto; padding: clamp(1.25rem, 4vw, 4rem); }
  h1, h2, h3, p { margin-top: 0; }
  h1 { margin-bottom: .45rem; font-family: Georgia, serif; font-size: clamp(3rem, 8vw, 6.5rem); font-weight: 400; line-height: .86; letter-spacing: -.06em; }
  h2 { margin-bottom: 0; font-family: Georgia, serif; font-size: 2rem; font-weight: 400; }
  h3 { margin-bottom: .5rem; }
  .eyebrow { margin-bottom: .65rem; color: #74bd9c; font-size: .68rem; font-weight: 800; letter-spacing: .2em; }
  .lede { max-width: 44rem; color: #aebdb6; font-size: 1.05rem; }
  .masthead { display: flex; align-items: flex-end; justify-content: space-between; gap: 2rem; min-height: 15rem; padding-bottom: 2rem; border-bottom: 1px solid #34433d; }
  .source-tools { display: grid; gap: .65rem; width: min(25rem, 100%); }
  .source-badge { display: flex; gap: .75rem; width: 100%; padding: 1rem; border: 1px solid #39634f; background: #14231d; }
  .refresh { justify-self: end; padding: .55rem .8rem; border: 1px solid #587066; color: #e9efeb; background: #17201d; font: inherit; font-size: .78rem; cursor: pointer; }
  .refresh:hover:not(:disabled) { border-color: #74bd9c; background: #203129; }
  .refresh:disabled { cursor: wait; opacity: .65; }
  .source-badge.warning { border-color: #a97c45; background: #282015; }
  .source-badge .signal { flex: 0 0 auto; width: .7rem; height: .7rem; margin-top: .3rem; border-radius: 50%; background: #74d5a9; box-shadow: 0 0 1rem #74d5a9; }
  .source-badge.warning .signal { background: #e3a85d; box-shadow: 0 0 1rem #e3a85d; }
  .source-badge strong, .source-badge small { display: block; }
  .source-badge strong { text-transform: uppercase; letter-spacing: .12em; }
  .source-badge small { margin-top: .3rem; color: #c5d0cb; line-height: 1.35; }
  .summary { display: grid; grid-template-columns: repeat(4, 1fr); border-bottom: 1px solid #34433d; }
  .summary div { padding: 1.4rem 0; border-right: 1px solid #34433d; }
  .summary div:not(:first-child) { padding-left: 1.5rem; }
  .summary div:last-child { border-right: 0; }
  .summary span, .summary small { display: block; }
  .summary span { font-family: Georgia, serif; font-size: 2rem; }
  .summary small { color: #899991; }
  .layout { display: grid; grid-template-columns: minmax(0, 3fr) minmax(16rem, 1fr); gap: 3rem; padding: 4rem 0; }
  section { margin-bottom: 4rem; }
  .section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; margin-bottom: 1.5rem; }
  .section-heading.compact { margin-bottom: 1rem; }
  .timestamp { color: #7e8f87; font-family: ui-monospace, monospace; font-size: .7rem; }
  .cards { display: grid; gap: 1rem; }
  article { border: 1px solid #34433d; background: rgba(18, 25, 22, .9); }
  .opportunity { padding: 1.4rem; }
  .card-top, .machine-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
  .card-top { margin-bottom: 1.15rem; }
  .state { display: inline-flex; width: fit-content; padding: .25rem .55rem; border: 1px solid #53645c; color: #c7d3ce; font-size: .64rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
  .state-available, .state-ready { border-color: #4c9d76; color: #8be0b7; }
  .state-blocked, .state-needs_attention, .state-missing_affordance { border-color: #a45e55; color: #f4a69c; }
  .state-stale, .state-capacity_stale, .state-runtime_stale, .state-unknown, .state-unavailable { border-color: #9a774a; color: #e6b875; }
  .action { max-width: 52rem; color: #dae4df; font-size: 1.1rem; line-height: 1.55; }
  .meta { display: flex; flex-wrap: wrap; gap: .5rem 1.5rem; margin: 1rem 0; color: #899991; font-size: .75rem; text-transform: uppercase; letter-spacing: .08em; }
  .meta b { color: #dce6e1; }
  .missing { padding: .65rem .8rem; background: #241a18; color: #e7b0a8; font-size: .85rem; }
  details { margin-top: 1rem; }
  summary { color: #9ad9be; cursor: pointer; font-size: .85rem; }
  .checks { display: grid; gap: .75rem; padding: 0; list-style: none; }
  .checks li { display: grid; grid-template-columns: 4rem 1fr; gap: .75rem; padding-top: .75rem; border-top: 1px solid #28332f; }
  .checks p { margin: .25rem 0; color: #aebdb6; line-height: 1.4; }
  .result { font-size: .65rem; font-weight: 800; text-transform: uppercase; }
  .result-pass { color: #83d6af; } .result-fail { color: #f09b91; } .result-unknown { color: #e6b875; }
  .evidence-links { display: flex; flex-wrap: wrap; gap: .4rem; font-family: ui-monospace, monospace; font-size: .68rem; }
  .evidence-links span { color: #74847d; }
  .source-list { border-top: 1px solid #34433d; }
  .source-list div { display: grid; gap: .2rem; padding: 1rem 0; border-bottom: 1px solid #34433d; }
  .source-list span, .source-list small { color: #899991; }
  .boundaries { margin-top: 2rem; padding: 1rem; border-left: 2px solid #9a774a; background: #1c1913; }
  .boundaries li { margin-bottom: .55rem; color: #b9c4bf; line-height: 1.4; }
  .machine-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }
  .machine { padding: 1.2rem; }
  .machine h3 { font-family: Georgia, serif; font-size: 1.25rem; font-weight: 400; }
  dl { margin: 1.2rem 0; }
  dl div { display: flex; justify-content: space-between; gap: 1rem; padding: .4rem 0; border-bottom: 1px solid #28332f; }
  dt { color: #7f9088; } dd { margin: 0; text-align: right; }
  .capabilities { color: #9ad9be; font-family: ui-monospace, monospace; font-size: .72rem; }
  .lower-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 3rem; }
  .timeline, .evidence-index { margin: 0; padding: 0; list-style: none; border-top: 1px solid #34433d; }
  .timeline li, .evidence-index li { display: grid; gap: .25rem; padding: 1rem 0; border-bottom: 1px solid #34433d; }
  .timeline time, .timeline small, .evidence-index span { color: #87978f; font-size: .74rem; }
  .empty, .notice { display: grid; gap: .35rem; padding: 1.25rem; border: 1px dashed #53645c; color: #aebdb6; }
  .notice { margin: 3rem 0; }
  .notice.error { border-color: #a45e55; color: #f4a69c; }
  @media (max-width: 900px) {
    .masthead { align-items: stretch; flex-direction: column; }
    .layout, .lower-grid { grid-template-columns: 1fr; gap: 1rem; }
    .machine-grid { grid-template-columns: repeat(2, 1fr); }
  }
  @media (max-width: 600px) {
    main { padding: 1rem; }
    .summary { grid-template-columns: 1fr 1fr; }
    .summary div:nth-child(2) { border-right: 0; }
    .summary div:nth-child(3) { padding-left: 0; }
    .machine-grid { grid-template-columns: 1fr; }
    .section-heading { align-items: flex-start; flex-direction: column; }
    .card-top { align-items: flex-start; flex-direction: column; }
  }
</style>
