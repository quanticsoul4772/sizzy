<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe, fmtTime } from '../events.js';

  // B3.8: maintenance loop — ticks + actions grouped by cycle_kind (consolidate/prune/audit/synthesize).
  let feed = $state([]); // {event_type, cycle_kind, description}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    let cycle_kind, description;
    if (msg.event_type === 'cap_ratification_recommended') {
      cycle_kind = 'cap';
      description = `${p.task_class}: ${p.action} → ${p.recommended_cap} (n=${p.samples})`;
    } else {
      cycle_kind = p.cycle_kind;
      description = msg.event_type === 'maintenance_action' ? p.action_description : '(tick)';
    }
    feed = [...feed, { event_type: msg.event_type, cycle_kind, description, received_at: msg.received_at }].slice(-50);
  }

  onMount(() => {
    unsubscribe = subscribe(['maintenance_tick', 'maintenance_action', 'cap_ratification_recommended'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Maintenance</h2>
  <small>proj_maintenance · cap_ratification_recommended</small>
  {#if feed.length === 0}
    <p>no maintenance yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each feed as e, i (i)}
        <li><span class="ts">{fmtTime(e.received_at)}</span> <span>[{e.cycle_kind}]</span> {e.description}</li>
      {/each}
    </ul>
  {/if}
</section>
