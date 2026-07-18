<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe, fmtTime } from '../events.js';

  // B5.6: federated trusted memory — local vs imported entries; imported (verified_locally=0) are shown
  // prominently as "pending verification" until a memory_entry_verified promotes them (Inv 17).
  const PROJECT = 'devharness'; // local-vs-imported is rendered relative to this project's identity
  let trusted = $state(0);
  let pendingVerification = $state(0);
  let feed = $state([]); // {label, detail}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    let label = '', detail = '';
    if (msg.event_type === 'memory_entry_created') {
      const local = p.source_project === PROJECT;
      if (local) { trusted += 1; label = 'created:local-trusted'; }
      else { pendingVerification += 1; label = 'imported:pending-verification'; }
      detail = `${p.entry_type} ← ${p.source_project}`;
    } else {
      pendingVerification = Math.max(0, pendingVerification - 1);
      trusted += 1;
      label = 'verified';
      detail = `${p.entry_id} by ${p.verified_by}`;
    }
    feed = [...feed, { label, detail, received_at: msg.received_at }].slice(-50);
  }

  onMount(() => {
    unsubscribe = subscribe(['memory_entry_created', 'memory_entry_verified'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Trusted Memory</h2>
  <small>memory_entry_created · memory_entry_verified</small>
  <p>trusted: {trusted} · pending verification: {pendingVerification}</p>
  {#if feed.length === 0}
    <p>no trusted memory entries yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each feed as e, i (i)}
        <li><span class="ts">{fmtTime(e.received_at)}</span> <span>[{e.label}]</span> {e.detail}</li>
      {/each}
    </ul>
  {/if}
</section>
