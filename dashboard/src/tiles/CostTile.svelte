<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe } from '../events.js';

  // rev 0.3.81: per-role LLM spend. cost_spent has fed proj_cost since rev 0.3.60, but the tile was
  // a feedless placeholder — this surfaces the running per-role total + grand total live over SSE.
  // rev 0.4.2: keyed by role · model (cost_spent carries the model that billed the spend), so tier
  // routing is visible on the tile; a pre-0.4.2 event without a model keys by bare role.
  let byRole = $state({}); // "role · model" -> cumulative spent_usd
  let total = $state(0);
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    const amt = Number(p.amount_usd) || 0;
    const key = `${p.role}${p.model ? ' · ' + p.model : ''}`;
    byRole = { ...byRole, [key]: (byRole[key] || 0) + amt };
    total += amt;
  }

  onMount(() => {
    unsubscribe = subscribe(['cost_spent'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Cost (LLM spend)</h2>
  <small>cost_spent events</small>
  {#if total === 0}
    <p>no spend yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each Object.entries(byRole).sort((a, b) => b[1] - a[1]) as [role, spent] (role)}
        <li><span>{role}</span> — ${spent.toFixed(4)}</li>
      {/each}
    </ul>
    <p><strong>total: ${total.toFixed(4)}</strong></p>
  {/if}
</section>
