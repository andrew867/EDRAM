import ghidra.app.decompiler.DecompInterface;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

public class ReviewEdram extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String programName = currentProgram.getName();
        boolean ae = programName.startsWith("EDRMAE11");
        Map<Long, String> entries = new LinkedHashMap<>();
        entries.put(0x412L, "load_entry_stub");
        entries.put(0x418L, "alternate_entry_stub");
        entries.put(ae ? 0x11f6eL : 0x11f5eL, "application_entry");
        entries.put(ae ? 0x11e88L : 0x11e78L, "alternate_application_entry");
        entries.put(0xea10L, "copy_bytes");
        entries.put(0xeacaL, "sum_big_endian_words");
        entries.put(0x117deL, "register_loaded_announcement_banks");
        entries.put(0x11978L, "write_announcement_load_payload");
        entries.put(ae ? 0x11b0aL : 0x11afaL, "initialize_announcement_directory");
        entries.put(ae ? 0x1a400L : 0x1a42eL, "compare_announcement_bank_checksums");
        entries.put(ae ? 0x1a79cL : 0x1a7caL, "clear_256_byte_pages");
        entries.put(ae ? 0x1a7aeL : 0x1a7dcL, "copy_256_byte_pages");
        boolean seed = getScriptArgs()[0].equals("seed");
        if (seed) {
            for (Map.Entry<Long, String> entry : entries.entrySet()) {
                Address address = toAddr(entry.getKey());
                disassemble(address);
                Function function = getFunctionAt(address);
                if (function == null) {
                    function = createFunction(address, entry.getValue());
                }
                if (function != null) {
                    function.setName(entry.getValue(), SourceType.USER_DEFINED);
                }
            }
            return;
        }

        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        Path output = Path.of(getScriptArgs()[1], programName.replace(".m68k.elf", "") + ".ghidra.c.txt");
        try (PrintWriter writer = new PrintWriter(Files.newBufferedWriter(output, StandardCharsets.UTF_8))) {
            writer.printf("// Ghidra decompilation of %s%n", programName);
            writer.printf("// %s, %d functions discovered. Names assigned during review.%n",
                currentProgram.getLanguageID(), currentProgram.getFunctionManager().getFunctionCount());
            writer.println("// Addresses outside the supplied load and the inferred types need validation.");
            for (Map.Entry<Long, String> entry : entries.entrySet()) {
                Address address = toAddr(entry.getKey());
                Function function = getFunctionAt(address);
                writer.printf("%n// %s at %s%n", entry.getValue(), address);
                if (function == null) {
                    writer.println("// Function could not be recovered");
                    continue;
                }
                var result = decompiler.decompileFunction(function, 30, monitor);
                if (result.decompileCompleted() && result.getDecompiledFunction() != null) {
                    writer.println(result.getDecompiledFunction().getC());
                } else {
                    writer.println("// " + result.getErrorMessage());
                }
            }
        } finally {
            decompiler.dispose();
        }
    }
}
