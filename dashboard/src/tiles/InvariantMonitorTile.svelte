<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe } from '../events.js';

  // rev 0.3.87: the live invariant monitor. The monitor sweeps the event log after each build and emits
  // invariant_violated the moment a behavioral invariant breaks (turning the 18 test-time invariants into
  // live guards). This tile surfaces those breaches so a silent failure (e.g. a task with no terminal)
  // becomes loud.
  let violations = $state([]); // most-recent first
  let byInvariant = $state({}); // invariant_number -> count
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    violations = [{ n: p.invariant_number, property: p.property, task: p.task_id, detail: p.detail }, ...violations].slice(0, 20);
    byInvariant = { ...byInvariant, [p.invariant_number]: (byInvariant[p.invariant_number] || 0) + 1 };
  }

  onMount(() => {
    unsubscribe = subscribe(['invariant_violated'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Invariant monitor</h2>
  <small>invariant_violated</small>
  {#if violations.length === 0}
    <p>no violations{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <p><strong>{violations.length} violation{violations.length === 1 ? '' : 's'}</strong>
      ({Object.entries(byInvariant).sort((a, b) => a[0] - b[0]).map(([n, c]) => `Inv ${n}×${c}`).join(', ')})</p>
    <ul>
      {#each violations as v}
        <li>⚠ <strong>Inv {v.n}</strong> — {v.property}{v.task ? ` (${v.task})` : ''}</li>
      {/each}
    </ul>
  {/if}
</section>
