use eframe::egui;
use rfd::FileDialog;
use std::fs;
use dirs;
use std::io::BufReader;
use std::thread;
use std::time::Duration;


fn main() -> eframe::Result<()> {

    let (_stream, handle) = rodio::OutputStream::try_default().unwrap();
    let sink = rodio::Sink::try_new(&handle).unwrap();

    let file = std::fs::File::open("/home/bkelldog/Coding/Typewriter/typewriter_click.wav").unwrap();
    let click = handle.play_once(BufReader::new(file)).unwrap();
    click.set_volume(0.9);
    println!("Started click");

    let options = eframe::NativeOptions::default();
    eframe::run_native(
        "Typwriter",
        options,
        Box::new(|_cc| Ok(Box::new(Typewriter::default()))),
    );

    Ok(())
}

struct Typewriter {
    text: String,
    file_path: Option<std::path::PathBuf>,
    last_key: Option<egui::Key>,
}

impl Default for Typewriter {
    fn default() -> Self {
        Self {
            text: String::new(),
            file_path: None,
            last_key: None,
        }
    }
}


impl eframe::App for Typewriter {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {

        // Key press detection
        for key in egui::Key::ALL {
            if ctx.input(|i| i.key_pressed(*key)) {
                self.last_key = Some(*key);
                println!("Key pressed: {:?}", *key);
            }
        }
        
        // Add top tool bar
        egui::TopBottomPanel::top("top_panel").show(ctx, |ui| {
            egui::menu::bar(ui, |ui| {
                ui.menu_button("File", |ui| {

                    // Create Open button
                    if ui.button("Open").clicked() {
                        if let Some(path) = FileDialog::new().add_filter("Text", &["txt"]).pick_file() {
                            match fs::read_to_string(&path) {
                                Ok(content) => {
                                    self.text = content;
                                    self.file_path = Some(path); // if you track file state
                                }
                                Err(err) => {
                                    eprintln!("Failed to open file: {}", err);
                                }
                            }
                        }
                    }

                    // Create Save button
                    if ui.button("Save").clicked() {
                        self.save_file();
                    }
                });
            });
        });

        // Add central section with text field
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.add(                                            // Central text field
                egui::TextEdit::multiline(&mut self.text)
                    .desired_rows(20)
                    .desired_width(f32::INFINITY)
                    .lock_focus(true),
            );

            // Display the last pressed key
            if let Some(key) = self.last_key {
                ui.label(format!("Last key pressed: {:?}", key));
            }
        });
    }
}

impl Typewriter {
    fn save_file(&mut self) {
        if let Some(path) = rfd::FileDialog::new()
            .set_directory(dirs::download_dir().unwrap_or_else(|| std::path::PathBuf::from(".")))
            .save_file()
        {
            let mut path = path;
            if path.extension().is_none() {
                path.set_extension("txt");
            }
            if let Err(err) = std::fs::write(&path, &self.text) {
                eprintln!("Failed to save file: {err}");
            }
        }
    }
}