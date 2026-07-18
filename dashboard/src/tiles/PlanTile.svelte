<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe } from '../events.js';

  // B1.6: plan_drafted — plans with task counts.
  let plans = $state([]); // {plan_id, spec_id, task_count}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    plans = [
      ...plans.filter((pl) => pl.plan_id !== p.plan_id),
      { plan_id: p.plan_id, spec_id: p.spec_id, task_count: p.task_count },
    ];
  }

  onMount(() => {
    unsubscribe = subscribe(['plan_drafted'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Plans</h2>
  <small>proj_plan</small>
  {#if plans.length === 0}
    <p>no plans yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each plans as pl (pl.plan_id)}
        <li><small>{pl.plan_id}</small> — {pl.task_count} task(s) from spec {pl.spec_id}</li>
      {/each}
    </ul>
  {/if}
</section>
