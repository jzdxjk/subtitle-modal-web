using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Emby.SubtitleAssistant.Core;
using Xunit;

namespace Emby.SubtitleAssistant.Tests;

public class SearchPoolContractTests
{
    [Fact]
    public async Task ActualGeneratedAliasesAreAcceptedByPoolWorkSearch()
    {
        var paths = new[]
        {
            "SSIS-157-LTX【2021-08-19】（小宵虎南）出差和一直蔑视的中年性骚扰上司共处一室…直到早晨的绝伦性交HCUP新入社员.mp4",
            "SSIS-157-c-无码破解.mp4", "ssis157.mp4", "SSIS_157.mp4", "SAVR-00143.mp4",
            "MIUM-00123.mp4", "300MIUM00123.mp4", "GANA-00123.mp4", "200GANA-00123.mp4",
            "JNT-00123.mp4", "390JNT-00123.mp4", "IDOL-00123.mp4", "250IDOL-00123.mp4", "259LUXU-00123.mp4", "LUXU-00123.mp4",
            "FC2-PPV-0123456.mp4", "FC2PPV-0123456.mp4", "FC2-0123456.mp4",
            "1pondo_010203_004.mp4", "10musume-010203-004.mp4", "carib-010203_004.mp4",
            "caribbeancom-010203-004.mp4", "pacopacomama_010203_004.mp4", "010203-004.mp4",
            "HEYZO-0123.mp4", "HEYZO_0123.mp4", "HEYZO0123.mp4", "N0123.mp4", "N-0123.mp4", "N_0123.mp4"
        };
        var batches = paths.Select(path => new { path, codes = MediaIdentifier.TryParse(path)?.QueryVariants }).ToArray();
        Assert.All(batches, batch => Assert.NotNull(batch.codes));
        var cases = batches.Cast<object>().ToList();
        void Seeded(string path, string[] matching, string[] rejected)
        {
            var identifier = MediaIdentifier.TryParse(path);
            Assert.NotNull(identifier);
            Assert.All(matching, code => Assert.True(identifier.Matches(code), path + " should match stored " + code));
            Assert.All(rejected.Where(code => !code.EndsWith("x", StringComparison.Ordinal)), code => Assert.False(identifier.Matches(code), path + " must reject neighboring " + code));
            cases.Add(new { path, codes = identifier.QueryVariants, seedMatches = matching, seedRejects = rejected });
        }
        Seeded("SAVR-00143.mp4", new[] { "savr-143", "savr-00143", "savr-00000143-cd2" }, new[] { "savr-144", "savr-00143-cd2x", "savr-001430" });
        Seeded("300MIUM-00123.mp4", new[] { "mium-123", "mium-000123-cd2", "300mium-00123" }, new[] { "mium-124", "300mium-00124" });
        Seeded("MIUM-00123.mp4", new[] { "mium-123", "mium-000123-cd2", "300mium-00123" }, new[] { "mium-124" });
        Seeded("259LUXU-00123.mp4", new[] { "259luxu-00123", "luxu-00123-cd1" }, new[] { "luxu-00124" });
        Seeded("T28-1.mp4", new[] { "t28-1", "t28-0000001-cd2" }, new[] { "t28-2" });
        Seeded("SSIS-1.mp4", new[] { "ssis-001", "ssis-00000001-cd1" }, new[] { "ssis-2" });
        Seeded("SSIS-1234567.mp4", new[] { "ssis-1234567", "ssis-01234567-cd2" }, new[] { "ssis-1234568" });
        Seeded("FC2-123.mp4", new[] { "fc2-123", "fc2-00000123-cd1" }, new[] { "fc2-124" });
        Seeded("FC2-123456789012.mp4", new[] { "fc2-123456789012", "fc2-123456789012-cd2" }, new[] { "fc2-123456789013" });
        Seeded("010203-04.mp4", new[] { "010203-04", "010203-04-cd2" }, new[] { "010203-00004", "010203-05" });
        Seeded("010203-00004.mp4", new[] { "010203-00004", "010203-00004-cd1" }, new[] { "010203-04", "010203-00005" });
        Seeded("HEYZO-0123.mp4", new[] { "heyzo-123", "heyzo-00000123-cd1" }, new[] { "heyzo-124" });
        Seeded("N0123.mp4", new[] { "n-123", "n-00000123-cd1" }, new[] { "n-124" });
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory != null && !File.Exists(Path.Combine(directory.FullName, "subtitle-pool", "src", "index.js"))) directory = directory.Parent;
        Assert.NotNull(directory);
        var script = """
            import assert from 'node:assert/strict';
            import { readFileSync } from 'node:fs';
            import { DatabaseSync } from 'node:sqlite';
            import { pathToFileURL } from 'node:url';
            const workerUrl = pathToFileURL(process.argv[1]);
            const { default: worker } = await import(workerUrl.href);
            const db = new DatabaseSync(':memory:');
            db.exec(readFileSync(new URL('../migrations/0001_init.sql', workerUrl), 'utf8'));
            db.exec(readFileSync(new URL('../migrations/0002_public_upload_limits.sql', workerUrl), 'utf8'));
            const env = { DB: { prepare(sql) { return { bind(...args) { return { async all() { return { results: db.prepare(sql).all(...args) }; } }; } }; } } };
            let input = '';
            for await (const chunk of process.stdin) input += chunk;
            const batches = JSON.parse(input);
            for (const batch of batches) {
              db.exec('DELETE FROM subtitle_items');
              const wanted = batch.seedMatches ?? [];
              const rejected = batch.seedRejects ?? [];
              const insert = db.prepare(`INSERT INTO subtitle_items
                (id,canonical_code,display_code,language,format,duration_seconds,size_bytes,sha256,r2_key,uploaded_at,status)
                VALUES (?, ?, ?, 'zh', 'srt', 120, 100, ?, ?, 1000, 'active')`);
              for (const [i, code] of wanted.entries()) insert.run(`wanted-${i}`, code, code.toUpperCase(), `wanted-${i}`, `wanted-${i}.srt`);
              for (const [i, code] of rejected.entries()) insert.run(`rejected-${i}`, code, code.toUpperCase(), `rejected-${i}`, `rejected-${i}.srt`);
              const url = new URL('https://pool.test/api/v1/subtitles/search?match=work');
              for (const code of batch.codes) url.searchParams.append('codes', code);
              const response = await worker.fetch(new Request(url), env);
              const body = await response.json();
              assert.equal(response.status, 200, JSON.stringify({ path: batch.path, codes: batch.codes, body }));
              assert.ok(Array.isArray(body.items));
              assert.deepEqual(body.items.map(item => item.id).sort(), wanted.map((_, i) => `wanted-${i}`).sort(), JSON.stringify({ path: batch.path, body }));
            }
            console.log(JSON.stringify({ acceptedBatches: batches.length }));
            db.close();
            """;
        var start = new ProcessStartInfo("node") { RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false,
            StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
        start.ArgumentList.Add("--input-type=module");
        start.ArgumentList.Add("--eval");
        start.ArgumentList.Add(script);
        start.ArgumentList.Add(Path.Combine(directory.FullName, "subtitle-pool", "src", "index.js"));
        using var process = Process.Start(start);
        var outputTask = process.StandardOutput.ReadToEndAsync();
        var errorTask = process.StandardError.ReadToEndAsync();
        await process.StandardInput.WriteAsync(JsonSerializer.Serialize(cases));
        process.StandardInput.Close();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        await process.WaitForExitAsync(timeout.Token);
        var output = await outputTask;
        var error = await errorTask;
        Assert.True(process.ExitCode == 0, error + output);
        Assert.Equal(cases.Count, JsonDocument.Parse(output).RootElement.GetProperty("acceptedBatches").GetInt32());
    }
}
