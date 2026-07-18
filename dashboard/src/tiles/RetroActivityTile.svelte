<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe, fmtTime } from '../events.js';

  // B5.6: retro activity — recent retro_run events; surfaces the T0-matched vs LLM-residue proportion.
  let runs = $state(0);
  let t0Runs = $state(0);
  let llmRuns = $state(0);
  let feed = $state([]); // {label, detail}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    runs += 1;
    const t0 = (p.t0_matched_signatures || []).length;
    if (t0 > 0) t0Runs += 1;
    if (p.llm_invoked) llmRuns += 1;
    const label = p.llm_invoked ? 'llm-residue' : (t0 > 0 ? 't0-matched' : 'no-match');
    const detail = `${p.terminal_kind || ''} · t0=${t0} · candidates=${p.candidates_emitted ?? 0}`;
    feed = [...feed, { label, detail, received_at: msg.received_at }].slice(-50);
  }

  onMount(() => {
    unsubscribe = subscribe(['retro_run'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Retro Activity</h2>
  <small>retro_run</small>
  <p>runs: {runs} · t0-matched: {t0Runs} · llm-residue: {llmRuns}</p>
  {#if feed.length === 0}
    <p>no retro activity yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each feed as e, i (i)}
        <li><span class="ts">{fmtTime(e.received_at)}</span> <span>[{e.label}]</span> {e.detail}</li>
      {/each}
    </ul>
  {/if}
</section>
