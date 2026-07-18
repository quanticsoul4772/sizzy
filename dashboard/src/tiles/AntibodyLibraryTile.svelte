<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe, fmtTime } from '../events.js';

  // B5.6: active antibody library — size + recent additions + revoked count.
  let active = $state(0);
  let revoked = $state(0);
  let feed = $state([]); // {label, detail}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    let label = '', detail = '';
    if (msg.event_type === 'antibody_added') {
      active += 1;
      label = 'added';
      detail = `${p.pattern_text} ← ${p.source_candidate_id}`;
    } else {
      active = Math.max(0, active - 1);
      revoked += 1;
      label = 'revoked';
      detail = `#${p.antibody_row_id}: ${p.reason}`;
    }
    feed = [...feed, { label, detail, received_at: msg.received_at }].slice(-50);
  }

  onMount(() => {
    unsubscribe = subscribe(['antibody_added', 'antibody_revoked'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Antibody Library</h2>
  <small>antibody_added · antibody_revoked</small>
  <p>active: {active} · revoked: {revoked}</p>
  {#if feed.length === 0}
    <p>no antibody library entries yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each feed as e, i (i)}
        <li><span class="ts">{fmtTime(e.received_at)}</span> <span>[{e.label}]</span> {e.detail}</li>
      {/each}
    </ul>
  {/if}
</section>
