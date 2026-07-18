<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe, fmtTime } from '../events.js';

  // B2.9: developer activity feed — task_started / task_dispatched / write_attempted / write_applied.
  let feed = $state([]); // {event_type, task_id, target_path, predicted, observed}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    feed = [
      ...feed,
      {
        event_type: msg.event_type,
        task_id: p.task_id,
        target_path: p.target_path ?? '',
        predicted: p.predicted_success,
        observed: p.observed_success,
        received_at: msg.received_at,
      },
    ].slice(-50);
  }

  onMount(() => {
    unsubscribe = subscribe(
      ['task_started', 'task_dispatched', 'write_attempted', 'write_applied'],
      apply,
      () => (connected = true),
    );
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Developer activity</h2>
  <small>proj_developer_activity</small>
  {#if feed.length === 0}
    <p>no developer activity yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each feed as e, i (i)}
        <li>
          <span class="ts">{fmtTime(e.received_at)}</span> <span>{e.event_type}</span> {e.task_id}{e.target_path ? ` — ${e.target_path}` : ''}
          {#if e.predicted !== undefined && e.predicted !== null}<small> pred {e.predicted}</small>{/if}
          {#if e.observed !== undefined && e.observed !== null}<small> obs {e.observed}</small>{/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>
