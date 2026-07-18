<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe, fmtTime } from './events.js';

  let { title, table, eventTypes } = $props();

  let rows = $state([]);
  let connected = $state(false);
  let unsubscribe;

  onMount(() => {
    if (eventTypes.length === 0) return;
    unsubscribe = subscribe(
      eventTypes,
      (msg) => {
        rows = [...rows, msg].slice(-50);
      },
      () => {
        connected = true;
      }
    );
  });

  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>{title}</h2>
  <small>{table}</small>
  {#if eventTypes.length === 0}
    <p>no live event feed for this projection</p>
  {:else if rows.length === 0}
    <p>no {title.toLowerCase()} yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <table>
      <thead>
        <tr><th>time</th><th>seq</th><th>event_type</th><th>payload</th></tr>
      </thead>
      <tbody>
        {#each rows as row (row.seq)}
          <tr>
            <td>{fmtTime(row.received_at)}</td>
            <td>{row.seq}</td>
            <td>{row.event_type}</td>
            <td class="payload">{JSON.stringify(row.payload)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>
