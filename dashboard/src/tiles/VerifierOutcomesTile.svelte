<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe } from '../events.js';

  // B2.9: verifier outcomes — verifier_outcome (pass/fail + evidence summary).
  let outcomes = $state([]); // {task_id, verifier, passed}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    outcomes = [...outcomes, { task_id: p.task_id, verifier: p.verifier, passed: !!p.passed }].slice(-50);
  }

  onMount(() => {
    unsubscribe = subscribe(['verifier_outcome'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Verifier outcomes</h2>
  <small>proj_verifier_outcomes</small>
  {#if outcomes.length === 0}
    <p>no verifier outcomes yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each outcomes as o, i (i)}
        <li><span>{o.passed ? '[pass]' : '[fail]'}</span> {o.verifier} — {o.task_id}</li>
      {/each}
    </ul>
  {/if}
</section>
